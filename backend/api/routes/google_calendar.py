"""Google Calendar integration routes — OAuth2 + event sync."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Event, EventType, User
from backend.services.calendar_blocks_sync import create_blocks_calendar, delete_blocks_calendar, forget_blocks
from backend.services.google_calendar_service import (
    BLOCKS_SCOPE,
    SCOPES,
    authorization_needs_reconnect,
    connection_status,
    encrypt_refresh_token,
    exchange_code,
    fetch_events,
    get_auth_url,
)
from backend.services.google_oauth import plain_refresh_token, revoke_token
from backend.services.temporal import business_zone, utc_isoformat, utc_now_naive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ── Schemas ─────────────────────────────────────────────────

class CalendarStatus(BaseModel):
    connected: bool
    connection_status: Literal["connected", "disconnected", "reconnect_required"] = "disconnected"
    calendar_id: str | None = None
    meeting_alerts: dict | None = None
    last_synced_at: str | None = None
    # Bloques de trabajo publicados en su calendario "The Agency".
    blocks_calendar: bool = False


class BlocksDisable(BaseModel):
    delete_calendar: bool = False


class CalendarDisconnect(BaseModel):
    delete_blocks_calendar: bool = False


class MeetingAlertSettings(BaseModel):
    minutes_before: int = 30
    discord_dm: bool = True
    extension: bool = True


class EventResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    # Horas civiles de la agencia sin zona (como se guardan).
    start_time: datetime
    end_time: datetime | None = None
    is_all_day: bool = False
    source: str = "manual"
    google_event_id: str | None = None

    model_config = {"from_attributes": True}


class NextMeeting(BaseModel):
    id: int
    title: str
    date: str
    time: str
    source: Literal["manual", "google"]


class NextMeetingResponse(BaseModel):
    meeting: NextMeeting | None
    timezone: str
    connection_status: Literal["connected", "disconnected", "reconnect_required"]
    last_synced_at: str | None


# ── OAuth2 Flow ─────────────────────────────────────────────

@router.get("/auth-url")
async def calendar_auth_url(
    current_user: User = Depends(get_current_user),
):
    """Get the Google OAuth2 authorization URL."""
    _require_google_config()
    # Reconectar no puede quitar el permiso de los bloques a quien los publica.
    scopes = [*SCOPES, BLOCKS_SCOPE] if current_user.google_blocks_calendar_id else SCOPES
    url = get_auth_url(state=_sign_oauth_state(current_user.id), scopes=scopes)
    return {"url": url}


@router.get("/blocks/auth-url")
async def calendar_blocks_auth_url(
    current_user: User = Depends(get_current_user),
):
    """Permiso para publicar los bloques de trabajo (y leer reuniones, si aún no lo daba)."""
    _require_google_config()
    url = get_auth_url(state=_sign_oauth_state(current_user.id, "blocks"), scopes=[*SCOPES, BLOCKS_SCOPE])
    return {"url": url}


def _require_google_config() -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google Calendar no configurado en el servidor")


def _sign_oauth_state(user_id: int, purpose: str = "") -> str:
    """HMAC-signed, timestamped OAuth state (prevents account-link CSRF)."""
    msg = f"{user_id}:{int(time.time())}" + (f":{purpose}" if purpose else "")
    sig = hmac.new(settings.SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{msg}:{sig}".encode()).decode()


def _verify_oauth_state(state: str, max_age: int = 600) -> tuple[int, str]:
    """Return the signed (user_id, purpose), or raise ValueError if invalid/expired."""
    raw = base64.urlsafe_b64decode(state.encode()).decode()
    *parts, sig = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("bad state")
    expected = hmac.new(
        settings.SECRET_KEY.encode(), ":".join(parts).encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad signature")
    if time.time() - int(parts[1]) > max_age:
        raise ValueError("expired")
    return int(parts[0]), parts[2] if len(parts) == 3 else ""


@router.get("/callback")
async def calendar_callback(
    code: str | None = Query(None),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
    error: str | None = None,
):
    """Handle Google OAuth2 callback. Redirects to settings page."""
    # Verify signed state BEFORE doing any work (prevents OAuth account-link CSRF)
    try:
        user_id, purpose = _verify_oauth_state(state)
    except (ValueError, TypeError, Exception):
        return RedirectResponse(url="/settings?calendar=error&reason=invalid_state")

    # Google returns an error without a code when consent is cancelled or fails.
    # Keep provider details out of URLs and logs, after validating state first.
    if error == "access_denied":
        return RedirectResponse(url="/settings?calendar=cancelled")
    if error or not code:
        return RedirectResponse(url="/settings?calendar=error")

    try:
        tokens = await anyio.to_thread.run_sync(exchange_code, code)
    except Exception as e:
        logger.error("Google OAuth2 exchange failed (%s)", type(e).__name__)
        return RedirectResponse(url="/settings?calendar=error")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return RedirectResponse(url="/settings?calendar=error&reason=no_refresh_token")

    result = await db.execute(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return RedirectResponse(url="/settings?calendar=error")

    # Store encrypted refresh token
    user.google_refresh_token = encrypt_refresh_token(refresh_token)
    user.google_calendar_id = "primary"
    user.google_calendar_connected = True
    user.google_calendar_synced_at = None
    granted = set(tokens.get("scope", "").split())
    if user.google_blocks_calendar_id and BLOCKS_SCOPE not in granted:
        # Reconectó sin el permiso de los bloques: dejan de publicarse.
        await forget_blocks(db, user)

    await db.commit()
    logger.info("Google Calendar connected for user_id=%s", user_id)
    if purpose != "blocks":
        return RedirectResponse(url="/settings?calendar=connected")
    if BLOCKS_SCOPE not in granted:
        return RedirectResponse(url="/settings?calendar=blocks_denied")
    if user.google_blocks_calendar_id:
        return RedirectResponse(url="/settings?calendar=blocks_on")
    # Red fuera de la transacción: el token ya está guardado.
    encrypted = user.google_refresh_token
    try:
        calendar_id = await anyio.to_thread.run_sync(lambda: create_blocks_calendar(encrypted))
    except Exception as e:
        logger.error("Blocks calendar creation failed for user_id=%s (%s)", user_id, type(e).__name__)
        return RedirectResponse(url="/settings?calendar=error&reason=blocks_calendar")
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    user.google_blocks_calendar_id = calendar_id
    await db.commit()
    logger.info("Blocks calendar created for user_id=%s", user_id)
    return RedirectResponse(url="/settings?calendar=blocks_on")


async def _delete_blocks_calendar(encrypted_token: str | None, calendar_id: str | None, user_id: int) -> bool:
    if not encrypted_token or not calendar_id:
        return False
    try:
        await anyio.to_thread.run_sync(lambda: delete_blocks_calendar(encrypted_token, calendar_id))
        return True
    except Exception as e:
        logger.warning("Blocks calendar deletion failed for user_id=%s (%s)", user_id, type(e).__name__)
        return False


@router.post("/blocks/disable")
async def calendar_blocks_disable(
    body: BlocksDisable = BlocksDisable(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deja de publicar los bloques. Con ``delete_calendar``, borra además el
    calendario "The Agency" de su Google (si no, queda como estaba)."""
    user = await db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    token, calendar_id = user.google_refresh_token, user.google_blocks_calendar_id
    await forget_blocks(db, user)
    await db.commit()
    deleted = await _delete_blocks_calendar(token, calendar_id, user.id) if body.delete_calendar else False
    return {"ok": True, "calendar_deleted": deleted}


# ── Status & Disconnect ────────────────────────────────────

@router.get("/status", response_model=CalendarStatus)
async def calendar_status(
    current_user: User = Depends(get_current_user),
):
    """Check if user has Google Calendar connected."""
    effective_status = connection_status(current_user)
    return CalendarStatus(
        connected=effective_status == "connected",
        connection_status=effective_status,
        calendar_id=current_user.google_calendar_id,
        last_synced_at=utc_isoformat(current_user.google_calendar_synced_at),
        meeting_alerts=None,  # legacy preferences are history; effective policy lives in Avisos
        blocks_calendar=bool(current_user.google_blocks_calendar_id),
    )


@router.post("/disconnect")
async def calendar_disconnect(
    body: CalendarDisconnect = CalendarDisconnect(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Desconecta Google Calendar: borra el token, lo revoca en Google y borra
    los eventos importados de esa persona (son suyos y sólo servían para sus
    avisos). Los eventos manuales se quedan. Con ``delete_blocks_calendar``
    borra antes el calendario "The Agency" (después ya no habría permiso)."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    encrypted, blocks_calendar_id = user.google_refresh_token, user.google_blocks_calendar_id
    token = plain_refresh_token(user.google_refresh_token)
    await forget_blocks(db, user)
    user.google_refresh_token = None
    user.google_calendar_id = None
    user.google_calendar_connected = False
    user.google_calendar_synced_at = None
    # delete() masivo: no entra en el Deshacer, a propósito (Event tampoco está
    # en change_journal y un undo no podría devolver el permiso de Google).
    deleted = (await db.execute(
        delete(Event).where(Event.user_id == user.id, Event.source == "google")
    )).rowcount or 0
    await db.commit()
    # Después del commit: la copia local desaparece aunque Google no conteste.
    calendar_deleted = (await _delete_blocks_calendar(encrypted, blocks_calendar_id, user.id)
                        if body.delete_blocks_calendar else False)
    revoked = await revoke_token(token) if token else False
    if token and not revoked:
        logger.warning("Calendar de user_id=%s desconectado sin confirmación de revocación en Google", user.id)
    return {"ok": True, "google_revoked": revoked, "events_deleted": deleted,
            "blocks_calendar_deleted": calendar_deleted}


# ── Alert Settings ──────────────────────────────────────────

@router.put("/alerts", response_model=CalendarStatus)
async def update_alert_settings(
    body: MeetingAlertSettings,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update meeting alert preferences."""
    raise HTTPException(409, "Los avisos se configuran en Ajustes → Avisos; recarga la aplicación")


# ── Events ──────────────────────────────────────────────────

@router.get("/events", response_model=list[EventResponse])
async def list_calendar_events(
    date_from: Optional[date] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[date] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List synced calendar events for the current user."""
    query = select(Event).where(
        Event.user_id == current_user.id,
        Event.event_type == EventType.meeting,
    ).order_by(Event.start_time.asc())

    # Antes comparaba el texto con la columna y fallaba (nadie lo usaba); lo lee
    # la vista con horas de Mi agenda.
    if date_from:
        query = query.where(Event.start_time >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.where(Event.start_time < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))

    result = await db.execute(query.limit(100))
    return result.scalars().all()


@router.get("/next-meeting", response_model=NextMeetingResponse)
async def next_meeting(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the actor's next attributable meeting without triggering sync."""
    effective_status = connection_status(current_user)
    now_civil = (
        utc_now_naive().replace(tzinfo=timezone.utc)
        .astimezone(business_zone())
        .replace(tzinfo=None)
    )
    visible_source = and_(
        Event.source == "manual",
        Event.google_event_id.is_(None),
    )
    if current_user.google_refresh_token:
        configured_calendar_id = current_user.google_calendar_id or "primary"
        visible_source = or_(
            visible_source,
            and_(
                Event.source == "google",
                Event.google_event_id.is_not(None),
                Event.source_calendar_id == configured_calendar_id,
            ),
        )

    row = (await db.execute(
        select(Event.id, Event.title, Event.start_time, Event.source)
        .where(
            Event.user_id == current_user.id,
            Event.event_type == EventType.meeting,
            Event.is_all_day.is_(False),
            Event.start_time >= now_civil,
            visible_source,
        )
        .order_by(Event.start_time, Event.id)
        .limit(1)
    )).one_or_none()

    meeting = None
    if row is not None:
        meeting = NextMeeting(
            id=row.id,
            title=row.title,
            date=row.start_time.strftime("%Y-%m-%d"),
            time=row.start_time.strftime("%H:%M"),
            source=row.source,
        )
    return NextMeetingResponse(
        meeting=meeting,
        timezone=settings.AGENCY_TIMEZONE,
        connection_status=effective_status,
        last_synced_at=utc_isoformat(current_user.google_calendar_synced_at),
    )


@router.get("/upcoming")
async def upcoming_meetings(
    minutes: int = Query(60, ge=5, le=480),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get meetings starting in the next X minutes. Used by Chrome extension."""
    # Old extensions ignore consent, quiet hours and user-specific dedupe.
    # Current extension uses communication-schedules/extension-upcoming.
    return []


# ── Manual Sync Trigger ────────────────────────────────────

@router.post("/sync")
async def trigger_sync(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a calendar sync for the current user."""
    if connection_status(current_user) == "reconnect_required":
        raise HTTPException(409, "La autorización de Google Calendar ha caducado o se ha revocado. Reconecta el calendario en Ajustes")
    if not current_user.google_calendar_connected or not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar no conectado")

    count = await sync_user_events(db, current_user)
    return {"ok": True, "events_synced": count}


async def sync_user_events(db: AsyncSession, user: User) -> int:
    """Reconcile only a complete successful window for this user/calendar."""
    from backend.services.temporal import business_zone
    if not settings.SCHEDULED_COMMUNICATIONS_ENABLED:
        raise HTTPException(409, "La sincronización está pausada durante la actualización de avisos")
    if not user.is_active or not user.google_calendar_connected or not user.google_refresh_token:
        return 0
    # One full sync per user; a delayed older fetch cannot overwrite a newer one.
    # Advisory transaction lock does not lock the User row during provider IO.
    if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(76241312, :user_id)"), {"user_id": user.id}):
        raise HTTPException(409, "Ya hay una sincronización de este calendario en curso")
    refresh_token, calendar_id = user.google_refresh_token, user.google_calendar_id or "primary"
    now = utc_now_naive().replace(tzinfo=timezone.utc).astimezone(business_zone())
    # Del lunes de esta semana al final de la siguiente: la vista con horas de
    # Mi agenda enseña las reuniones de la semana entera (y la próxima). Si
    # cambias la ventana, cambia /privacidad (public-legal.tsx) en el mismo PR.
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today - timedelta(days=today.weekday())
    time_max = time_min + timedelta(days=14)
    try:
        events = await anyio.to_thread.run_sync(lambda: fetch_events(refresh_token, calendar_id=calendar_id, time_min=time_min, time_max=time_max))
        def civil(value):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(business_zone()).replace(tzinfo=None) if parsed.tzinfo else parsed
        # Validate ALL pages before any reconciliation. Malformed != empty.
        parsed_events = [(ev, None if ev.get("cancelled") else civil(ev["start_time"]),
                          civil(ev["end_time"]) if ev.get("end_time") else None) for ev in events]
    except Exception as error:
        if authorization_needs_reconnect(error):
            current = await db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
            # A delayed failure must never disable freshly reconnected credentials.
            if (current and current.is_active and current.google_calendar_connected
                and current.google_refresh_token == refresh_token
                and (current.google_calendar_id or "primary") == calendar_id):
                current.google_calendar_connected = False
                await db.commit()
                raise HTTPException(409, "La autorización de Google Calendar ha caducado o se ha revocado. Reconecta el calendario en Ajustes") from None
            raise HTTPException(409, "La conexión de calendario cambió durante la sincronización") from None
        raise HTTPException(502, "No se pudo completar la consulta al calendario; los eventos guardados se conservan") from None
    current = await db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not current.is_active or not current.google_calendar_connected or current.google_refresh_token != refresh_token or (current.google_calendar_id or "primary") != calendar_id:
        raise HTTPException(409, "La conexión de calendario cambió durante la sincronización")
    seen, synced = set(), 0
    for ev, start_dt, end_dt in parsed_events:
        gid = ev["google_event_id"]
        if ev.get("cancelled"):
            continue  # absence from the live set reconciles only the selected window
        seen.add(gid)
        existing = await db.scalar(select(Event).where(Event.user_id == user.id, Event.source == "google",
            Event.google_event_id == gid, or_(Event.source_calendar_id == calendar_id, Event.source_calendar_id.is_(None)))
            .order_by(Event.source_calendar_id.nulls_last()).limit(1))
        if existing is None:
            existing = Event(user_id=user.id, source="google", google_event_id=gid, event_type=EventType.meeting)
            db.add(existing)
        existing.source_calendar_id = calendar_id
        existing.title, existing.description = ev["title"], ev.get("description", "")
        existing.start_time, existing.end_time = start_dt, end_dt
        existing.is_all_day = ev.get("is_all_day", False)
        synced += 1
    await db.flush()
    await db.execute(delete(Event).where(Event.user_id == user.id, Event.source == "google", Event.source_calendar_id == calendar_id,
        Event.start_time >= time_min.replace(tzinfo=None), Event.start_time < time_max.replace(tzinfo=None), Event.google_event_id.notin_(seen)))
    current.google_calendar_synced_at = utc_now_naive()
    await db.commit()
    return synced
