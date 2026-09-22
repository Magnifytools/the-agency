from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, noload

from backend.db.database import get_db
from backend.db.models import DailyUpdate, DailyUpdateStatus, Delivery, DiscordSettings, User
from backend.api.deps import get_current_user
from backend.core.rate_limiter import ai_limiter
from backend.schemas.delivery import DeliveryReceipt
from backend.schemas.daily import (
    DailySubmitRequest,
    DailyEditRequest,
    DailyEnrichRequest,
    DailySendRequest,
    DailyPreviewResponse,
    DailyUpdateResponse,
    ParsedDailyData,
)
from backend.services.daily_parser import (
    parse_daily_update,
)
from backend.api.utils.db_helpers import safe_refresh
from backend.services.temporal import business_today, utc_now_naive

router = APIRouter(prefix="/api/dailys", tags=["daily-updates"])
logger = logging.getLogger(__name__)


def _to_response(d: DailyUpdate) -> DailyUpdateResponse:
    parsed = None
    if d.parsed_data:
        try:
            parsed = ParsedDailyData(**d.parsed_data)
        except Exception:
            parsed = None

    # Safely access user relationship — avoid lazy-load 500 in async
    try:
        user_name = d.user.full_name if d.user else None
    except Exception:
        user_name = None

    return DailyUpdateResponse(
        id=d.id,
        user_id=d.user_id,
        user_name=user_name,
        date=d.date,
        raw_text=d.raw_text,
        parsed_data=parsed,
        status=d.status,
        discord_sent_at=d.discord_sent_at,
        created_at=d.created_at,
        updated_at=d.updated_at,
        revision=d.revision,
        source_facts=d.source_facts or [],
    )


async def _lock_actor(db: AsyncSession, user_id: int) -> User:
    # Same recipient lock as permission writers; reacquire after enrichment.
    actor = (await db.execute(select(User).options(noload("*")).where(
        User.id == user_id,
    ).with_for_update(key_share=True).execution_options(populate_existing=True))).scalar_one_or_none()
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Tu sesión ya no tiene acceso. Vuelve a entrar.")
    return actor


async def _load_owned(db, daily_id, actor, *, lock=False):
    query = select(DailyUpdate).options(noload("*")).where(DailyUpdate.id == daily_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    daily = (await db.execute(query)).scalar_one_or_none()
    if daily is None:
        raise HTTPException(404, "Resumen diario no encontrado")
    if daily.user_id != actor.id and actor.role.value != "admin":
        raise HTTPException(403, "Solo puedes modificar tus propios resúmenes diarios")
    return daily


def _conflict(daily, *, exists=False):
    raise HTTPException(409, detail={
        "code": "daily_exists" if exists else "daily_conflict",
        "message": (f"Ya existe un resumen para el {daily.date.isoformat()}. Revisa el texto guardado."
                    if exists else "El resumen cambió en otra sesión. Revisa la versión guardada antes de continuar."),
        "current": _to_response(daily).model_dump(mode="json"),
    })


def _keys(facts):
    return [fact["key"] for fact in (facts or [])]


async def _selected_facts(db, actor, day, keys, *, previous=None):
    """Keep selected historical evidence; validate additions against real sources."""
    keys = list(dict.fromkeys(keys))
    known = {f["key"]: f for f in previous or []}
    if any(key not in known for key in keys):
        from backend.services.daily_facts import collect_daily_facts
        context = await collect_daily_facts(db, actor, day)
        known.update({f["key"]: f for f in context["facts"] if f["key"] not in known})
    if any(key not in known for key in keys):
        raise HTTPException(422, "Algunos hechos cambiaron. Actualiza las fuentes antes de añadirlos.")

    def event_key(key: str) -> str:
        base, separator, version = key.rpartition(":")
        if separator and len(version) == 16 and all(c in "0123456789abcdef" for c in version):
            return base
        return key

    event_keys = [event_key(key) for key in keys]
    if len(event_keys) != len(set(event_keys)):
        raise HTTPException(
            422,
            "El mismo hecho está seleccionado en dos versiones. Conserva la versión histórica o sustitúyela por la actual.",
        )
    return jsonable_encoder([known[key] for key in keys])


@router.post("", response_model=DailyUpdateResponse, status_code=status.HTTP_201_CREATED)
async def submit_daily(
    body: DailySubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save immediately. AI enrichment is a separate, explicit operation."""
    if not body.raw_text.strip() and not body.source_fact_keys:
        raise HTTPException(400, "Añade notas o selecciona al menos un hecho para el cierre")
    actor = await _lock_actor(db, current_user.id)
    update_date = body.date or business_today()
    keys = list(dict.fromkeys(body.source_fact_keys))
    existing = (await db.execute(select(DailyUpdate).options(noload("*")).where(
        DailyUpdate.user_id == actor.id, DailyUpdate.date == update_date,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if existing is not None:
        if existing.raw_text == body.raw_text and _keys(existing.source_facts) == keys:
            await db.commit()
            return _to_response(existing)
        _conflict(existing, exists=True)
    facts = await _selected_facts(db, actor, update_date, keys)
    daily = DailyUpdate(
        user_id=actor.id, date=update_date, raw_text=body.raw_text,
        parsed_data=None, source_facts=facts, revision=1,
        status=DailyUpdateStatus.draft, created_at=utc_now_naive(), updated_at=utc_now_naive(),
    )
    db.add(daily)
    await db.commit()
    await safe_refresh(db, daily, log_context="dailys")
    return _to_response(daily)


@router.get("", response_model=list[DailyUpdateResponse])
async def list_dailys(
    user_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List daily updates with optional filters."""
    q = select(DailyUpdate).options(selectinload(DailyUpdate.user)).order_by(DailyUpdate.date.desc(), DailyUpdate.created_at.desc())

    # Privacy: non-admin can only see their own dailys
    if current_user.role.value != "admin":
        q = q.where(DailyUpdate.user_id == current_user.id)
    elif user_id:
        q = q.where(DailyUpdate.user_id == user_id)
    if date_from:
        try:
            q = q.where(DailyUpdate.date >= date_type.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from debe tener formato YYYY-MM-DD")
    if date_to:
        try:
            q = q.where(DailyUpdate.date <= date_type.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to debe tener formato YYYY-MM-DD")

    q = q.limit(limit)
    result = await db.execute(q)
    return [_to_response(d) for d in result.scalars().all()]


@router.get("/prefill")
async def prefill_daily(
    date: date_type | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from backend.services.daily_facts import collect_daily_facts
    return await collect_daily_facts(db, current_user, date or business_today())


@router.get("/for-date", response_model=DailyUpdateResponse | None)
async def daily_for_date(
    date: date_type | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    daily = (await db.execute(select(DailyUpdate).options(selectinload(DailyUpdate.user)).where(
        DailyUpdate.user_id == current_user.id, DailyUpdate.date == (date or business_today()),
    ))).scalar_one_or_none()
    return _to_response(daily) if daily else None


@router.get("/{daily_id}", response_model=DailyUpdateResponse)
async def get_daily(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single daily update."""
    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")

    # Ownership check: only owner or admin
    if daily.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="No tienes acceso a este daily")

    return _to_response(daily)


@router.post("/{daily_id}/reparse", response_model=DailyUpdateResponse)
async def reparse_daily(
    daily_id: int,
    body: DailyEnrichRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enrich one saved revision without holding locks during the provider call."""
    actor = await _lock_actor(db, current_user.id)
    daily = await _load_owned(db, daily_id, actor, lock=True)
    if daily.revision != body.revision:
        _conflict(daily)
    if daily.status != DailyUpdateStatus.draft:
        raise HTTPException(409, "Este resumen ya se compartió. Conserva su versión enviada.")
    ai_limiter.check(actor.id, max_requests=10, window_seconds=60)
    revision, raw, facts = daily.revision, daily.raw_text, daily.source_facts or []
    actor_id = actor.id
    await db.commit()
    try:
        parsed = await parse_daily_update(raw, source_facts=facts)
        # Validate provider structure before publishing any change.
        normalized = ParsedDailyData.model_validate(parsed).model_dump()
        known = set(_keys(facts))
        task_rows = normalized["general"] + [task for project in normalized["projects"] for task in project["tasks"]]
        if any(set(task["fact_keys"]) - known for task in task_rows):
            raise ValueError("Unknown source fact returned by parser")
    except Exception:
        logger.exception("Daily enrichment failed; saved text retained: daily_id=%s", daily_id)
        raise HTTPException(502, "El texto sigue guardado. No se pudo estructurar; puedes reintentarlo.") from None
    actor = await _lock_actor(db, actor_id)
    daily = await _load_owned(db, daily_id, actor, lock=True)
    if daily.revision != revision or daily.raw_text != raw or daily.status != DailyUpdateStatus.draft:
        _conflict(daily)
    if daily.parsed_data != normalized:
        daily.parsed_data = normalized
        daily.status = DailyUpdateStatus.draft
        daily.revision += 1
        daily.updated_at = utc_now_naive()
    await db.commit()
    return _to_response(daily)


@router.put("/{daily_id}", response_model=DailyUpdateResponse)
async def edit_daily(
    daily_id: int,
    body: DailyEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a reviewed draft immediately, with optimistic revision control."""
    actor = await _lock_actor(db, current_user.id)
    daily = await _load_owned(db, daily_id, actor, lock=True)
    raw = body.raw_text if body.raw_text is not None else daily.raw_text
    keys = list(dict.fromkeys(body.source_fact_keys)) if body.source_fact_keys is not None else _keys(daily.source_facts)
    if not raw.strip() and not keys:
        raise HTTPException(400, "Añade notas o selecciona al menos un hecho para el cierre")
    parsed = (body.parsed_data.model_dump() if body.parsed_data is not None else
              None if raw != daily.raw_text or keys != _keys(daily.source_facts) else daily.parsed_data)
    unchanged = raw == daily.raw_text and keys == _keys(daily.source_facts) and parsed == daily.parsed_data
    if unchanged:
        await db.commit()
        return _to_response(daily)
    if daily.revision != body.revision:
        _conflict(daily)
    if daily.status != DailyUpdateStatus.draft:
        raise HTTPException(409, "Este resumen ya se compartió. Conserva su versión enviada.")
    subject = actor if daily.user_id == actor.id else await db.get(User, daily.user_id)
    facts = await _selected_facts(db, subject, daily.date, keys, previous=daily.source_facts)
    if parsed:
        rows = parsed["general"] + [t for p in parsed["projects"] for t in p["tasks"]]
        if any(set(t["fact_keys"]) - set(keys) for t in rows):
            raise HTTPException(422, "La redacción contiene fuentes no seleccionadas.")
    daily.raw_text, daily.source_facts, daily.parsed_data = raw, facts, parsed
    daily.revision += 1
    daily.updated_at = utc_now_naive()
    await db.commit()
    return _to_response(daily)


async def _resolve_channel_id(
    ds: DiscordSettings, webhook_url: str, http: "httpx.AsyncClient"
) -> str | None:
    """Get the channel_id for the webhook, using cached value or fetching from Discord."""
    if ds.channel_id:
        return ds.channel_id
    try:
        # GET /webhooks/{id}/{token} returns webhook info including channel_id
        resp = await http.get(webhook_url)
        if resp.status_code == 200:
            data = resp.json()
            channel_id = data.get("channel_id")
            if channel_id:
                ds.channel_id = channel_id
            return channel_id
    except Exception as e:
        logger.debug("Failed to resolve Discord channel_id from webhook: %s", e)
    return None


async def _send_daily_as_thread(
    webhook_url: str,
    bot_token: str,
    channel_id: str,
    header: str,
    body: str,
    http: "httpx.AsyncClient",
) -> bool:
    """Send daily as a Discord thread: post header via webhook, create thread, post body inside."""
    # Step 1: Send header message via webhook with ?wait=true to get message_id
    resp = await http.post(
        f"{webhook_url}?wait=true",
        json={
            "content": header,
            "username": "Daily Recap",
            "avatar_url": "https://agency.magnifytools.com/daily_recap_icon.png",
        },
    )
    if resp.status_code not in (200, 201):
        return False
    message_id = resp.json().get("id")
    if not message_id:
        return False

    # Step 2: Create thread from that message via Bot API
    thread_resp = await http.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/threads",
        headers={"Authorization": f"Bot {bot_token}"},
        json={"name": header[:100]},  # Thread name max 100 chars
    )
    if thread_resp.status_code not in (200, 201):
        logger.warning("Failed to create thread: %s %s", thread_resp.status_code, thread_resp.text[:200])
        # Header was already posted to Discord — treat as partial success
        return True
    thread_id = thread_resp.json().get("id")
    if not thread_id:
        return True  # Header posted, thread creation gave no ID

    # Step 3: Send body inside the thread via webhook
    # Discord messages max 2000 chars — split if needed
    if len(body) > 2000:
        body = body[:1997] + "..."
    resp = await http.post(
        f"{webhook_url}?wait=true&thread_id={thread_id}",
        json={
            "content": body,
            "username": "Daily Recap",
            "avatar_url": "https://agency.magnifytools.com/daily_recap_icon.png",
        },
    )
    if resp.status_code not in (200, 201):
        logger.warning("Failed to post thread body: %s", resp.status_code)
    # Header was posted — consider sent regardless of thread body result
    return True


@router.get("/{daily_id}/preview", response_model=DailyPreviewResponse)
async def preview_daily_for_discord(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Show the exact body that would be queued, without contacting Discord."""
    from backend.services import deliveries
    daily = await deliveries.authorize_source(db, "daily", daily_id, current_user, write=False)
    _, content = deliveries.render_snapshot("daily", daily)
    return DailyPreviewResponse(revision=daily.revision, content=content)


@router.post("/{daily_id}/send-discord", response_model=DeliveryReceipt, status_code=202)
async def send_daily_to_discord(
    daily_id: int,
    body: DailySendRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist an intent; the durable worker is the only daily sender."""
    from backend.services import deliveries
    row = await deliveries.enqueue(
        db, "daily", daily_id, current_user,
        custom_content=body.content if body else None,
        expected_revision=body.revision if body else None,
    )
    source = await deliveries.authorize_source(db, "daily", daily_id, current_user)
    return await deliveries.receipt(db, row, source)


@router.delete("/{daily_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_daily(
    daily_id: int,
    revision: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    actor = await _lock_actor(db, current_user.id)
    daily = await _load_owned(db, daily_id, actor, lock=True)
    if daily.revision != revision:
        _conflict(daily)
    if daily.status != DailyUpdateStatus.draft or await db.scalar(select(exists().where(
        Delivery.source_kind == "daily", Delivery.source_id == daily_id,
    ))):
        raise HTTPException(409, detail={
            "code": "traceability_required",
            "message": "Este resumen tiene historial de envío y se conserva junto a sus recibos.",
        })
    await db.delete(daily)
    await db.commit()
