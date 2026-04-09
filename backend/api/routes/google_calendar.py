"""Google Calendar integration routes — OAuth2 + event sync."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, Event, EventType
from backend.api.deps import get_current_user
from backend.config import settings
from backend.services.google_calendar_service import (
    get_auth_url, exchange_code, fetch_events, encrypt_refresh_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ── Schemas ─────────────────────────────────────────────────

class CalendarStatus(BaseModel):
    connected: bool
    calendar_id: str | None = None
    meeting_alerts: dict | None = None


class MeetingAlertSettings(BaseModel):
    minutes_before: int = 30
    discord_dm: bool = True
    extension: bool = True


class EventResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    start_time: str
    end_time: str | None = None
    is_all_day: bool = False
    source: str = "manual"
    google_event_id: str | None = None

    model_config = {"from_attributes": True}


# ── OAuth2 Flow ─────────────────────────────────────────────

@router.get("/auth-url")
async def calendar_auth_url(
    current_user: User = Depends(get_current_user),
):
    """Get the Google OAuth2 authorization URL."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google Calendar no configurado en el servidor")
    url = get_auth_url(state=str(current_user.id))
    return {"url": url}


@router.get("/callback")
async def calendar_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth2 callback. Redirects to settings page."""
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code missing")

    try:
        tokens = exchange_code(code)
    except Exception as e:
        logger.error("Google OAuth2 exchange failed: %s", e)
        return RedirectResponse(url="/settings?calendar=error")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return RedirectResponse(url="/settings?calendar=error&reason=no_refresh_token")

    # Find user from state (user_id)
    user_id = int(state) if state.isdigit() else None
    if not user_id:
        return RedirectResponse(url="/settings?calendar=error&reason=invalid_state")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/settings?calendar=error")

    # Store encrypted refresh token
    user.google_refresh_token = encrypt_refresh_token(refresh_token)
    user.google_calendar_id = "primary"
    user.google_calendar_connected = True

    # Set default meeting alert preferences if not set
    prefs = user.preferences or {}
    if "meeting_alerts" not in prefs:
        prefs["meeting_alerts"] = {
            "minutes_before": 30,
            "discord_dm": True,
            "extension": True,
        }
        user.preferences = prefs

    await db.commit()
    logger.info("Google Calendar connected for user_id=%s", user_id)
    return RedirectResponse(url="/settings?calendar=connected")


# ── Status & Disconnect ────────────────────────────────────

@router.get("/status", response_model=CalendarStatus)
async def calendar_status(
    current_user: User = Depends(get_current_user),
):
    """Check if user has Google Calendar connected."""
    prefs = current_user.preferences or {}
    return CalendarStatus(
        connected=current_user.google_calendar_connected or False,
        calendar_id=current_user.google_calendar_id,
        meeting_alerts=prefs.get("meeting_alerts"),
    )


@router.post("/disconnect")
async def calendar_disconnect(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disconnect Google Calendar."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    user.google_refresh_token = None
    user.google_calendar_id = None
    user.google_calendar_connected = False
    await db.commit()
    return {"ok": True}


# ── Alert Settings ──────────────────────────────────────────

@router.put("/alerts", response_model=CalendarStatus)
async def update_alert_settings(
    body: MeetingAlertSettings,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update meeting alert preferences."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one()
    prefs = user.preferences or {}
    prefs["meeting_alerts"] = body.model_dump()
    user.preferences = prefs
    await db.commit()
    return CalendarStatus(
        connected=user.google_calendar_connected or False,
        calendar_id=user.google_calendar_id,
        meeting_alerts=prefs["meeting_alerts"],
    )


# ── Events ──────────────────────────────────────────────────

@router.get("/events", response_model=list[EventResponse])
async def list_calendar_events(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List synced calendar events for the current user."""
    query = select(Event).where(
        Event.user_id == current_user.id,
        Event.event_type == EventType.meeting,
    ).order_by(Event.start_time.asc())

    if date_from:
        query = query.where(Event.start_time >= date_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to) + timedelta(days=1)
        query = query.where(Event.start_time < dt_to)

    result = await db.execute(query.limit(100))
    return result.scalars().all()


@router.get("/upcoming")
async def upcoming_meetings(
    minutes: int = Query(60, ge=5, le=480),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get meetings starting in the next X minutes. Used by Chrome extension."""
    now = datetime.now(MADRID_TZ).replace(tzinfo=None)
    cutoff = now + timedelta(minutes=minutes)

    result = await db.execute(
        select(Event).where(
            Event.user_id == current_user.id,
            Event.event_type == EventType.meeting,
            Event.start_time >= now,
            Event.start_time <= cutoff,
        ).order_by(Event.start_time.asc())
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "title": e.title,
            "start_time": e.start_time.isoformat(),
            "end_time": e.end_time.isoformat() if e.end_time else None,
            "minutes_until": int((e.start_time - now).total_seconds() / 60),
        }
        for e in events
    ]


# ── Manual Sync Trigger ────────────────────────────────────

@router.post("/sync")
async def trigger_sync(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a calendar sync for the current user."""
    if not current_user.google_calendar_connected or not current_user.google_refresh_token:
        raise HTTPException(status_code=400, detail="Google Calendar no conectado")

    count = await sync_user_events(db, current_user)
    return {"ok": True, "events_synced": count}


async def sync_user_events(db: AsyncSession, user: User) -> int:
    """Sync events from Google Calendar for a single user. Returns count of upserted events."""
    if not user.google_refresh_token:
        return 0

    now = datetime.now(MADRID_TZ).replace(tzinfo=None)
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = time_min + timedelta(days=7)

    events = fetch_events(
        user.google_refresh_token,
        calendar_id=user.google_calendar_id or "primary",
        time_min=time_min,
        time_max=time_max,
    )

    synced = 0
    seen_google_ids = set()

    for ev in events:
        gid = ev["google_event_id"]
        seen_google_ids.add(gid)

        # Parse datetime
        start_str = ev["start_time"]
        end_str = ev.get("end_time")
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).replace(tzinfo=None)
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None) if end_str and "T" in end_str else None
        except (ValueError, AttributeError):
            continue

        # Upsert by google_event_id
        result = await db.execute(
            select(Event).where(Event.google_event_id == gid)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title = ev["title"]
            existing.description = ev.get("description", "")
            existing.start_time = start_dt
            existing.end_time = end_dt
            existing.is_all_day = ev.get("is_all_day", False)
        else:
            new_event = Event(
                title=ev["title"],
                description=ev.get("description", ""),
                event_type=EventType.meeting,
                start_time=start_dt,
                end_time=end_dt,
                is_all_day=ev.get("is_all_day", False),
                user_id=user.id,
                google_event_id=gid,
                source="google",
            )
            db.add(new_event)
        synced += 1

    await db.commit()
    return synced
