from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import DailyUpdate, DailyUpdateStatus, DiscordSettings, User
from backend.api.deps import get_current_user
from backend.core.rate_limiter import ai_limiter
from backend.schemas.delivery import DeliveryReceipt
from backend.schemas.daily import (
    DailySubmitRequest,
    DailyEditRequest,
    DailyUpdateResponse,
    ParsedDailyData,
)
from backend.services.daily_parser import (
    parse_daily_update,
)
from backend.api.utils.db_helpers import safe_refresh
from backend.services.temporal import business_today, civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period

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
    )


@router.post("", response_model=DailyUpdateResponse, status_code=status.HTTP_201_CREATED)
async def submit_daily(
    body: DailySubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a daily update. The raw text is parsed by AI into structured data."""
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)

    if not body.raw_text.strip():
        raise HTTPException(status_code=400, detail="El texto del daily no puede estar vacío")

    update_date = body.date or business_today()

    # Check for duplicate daily on same date for this user
    existing = await db.execute(
        select(DailyUpdate).where(
            DailyUpdate.user_id == current_user.id,
            DailyUpdate.date == update_date,
        )
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un daily para el {update_date.isoformat()}. Edita o elimina el existente.",
        )

    # Guardar PRIMERO, parsear después. El orden inverso perdía el texto del
    # daily entero cada vez que fallaba la llamada a Claude, y dejaba al usuario
    # con un 502 y nada guardado. Además el INSERT tarda milisegundos: así la
    # fila está a salvo aunque el cliente corte la conexión (axios aborta a los
    # 30 s y el SDK de Anthropic puede tardar bastante más).
    daily = DailyUpdate(
        user_id=current_user.id,
        date=update_date,
        raw_text=body.raw_text,
        parsed_data=None,
        status=DailyUpdateStatus.draft,
    )
    db.add(daily)
    await db.commit()
    await safe_refresh(db, daily, log_context="dailys")

    # El parseo es un enriquecimiento, no un requisito: si falla, el daily queda
    # guardado sin estructurar y el usuario puede reintentarlo con POST
    # /dailys/{id}/reparse. Nunca es motivo para devolver un error.
    parsed = None
    try:
        parsed = await parse_daily_update(body.raw_text)
    except Exception:
        logger.exception("Error parseando daily_id=%s (queda guardado sin parsear)", daily.id)

    if parsed:
        daily.parsed_data = parsed
        await db.commit()
        await safe_refresh(db, daily, log_context="dailys")

    resp = _to_response(daily)
    resp.time_entries_created = 0
    return resp


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return tasks completed/moved today by the current user to pre-fill the daily."""
    from backend.db.models import Task, TaskStatus, TimeEntry
    today = business_today()
    completed_start, completed_end = civil_day_utc_bounds(today)

    # Tasks completed today by this user
    completed_result = await db.execute(
        select(Task)
        .options(selectinload(Task.client))
        .where(
            Task.assigned_to == current_user.id,
            Task.status == TaskStatus.completed,
            Task.completed_at >= completed_start,
            Task.completed_at < completed_end,
        )
    )
    completed = completed_result.scalars().all()

    # Tasks worked on today but not finished. Dos fuentes:
    #  - tiempo fichado hoy (requiere haber usado el timer)
    #  - estado "Avanzada" marcado hoy (gesto explícito de "hoy seguí con esto")
    te_result = await db.execute(
        select(Task)
        .options(selectinload(Task.client))
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .where(
            TimeEntry.user_id == current_user.id,
            time_entry_civil_period(today, today + timedelta(days=1)),
            Task.status != TaskStatus.completed,
        )
        .distinct()
    )
    worked_on = list(te_result.scalars().all())

    advanced_result = await db.execute(
        select(Task)
        .options(selectinload(Task.client))
        .where(
            Task.assigned_to == current_user.id,
            Task.status == TaskStatus.advanced,
            Task.advanced_at == today,
        )
    )
    seen_ids = {t.id for t in worked_on}
    worked_on += [t for t in advanced_result.scalars().all() if t.id not in seen_ids]

    # Build prefill text grouped by client
    lines: list[str] = []
    by_client: dict[str, list[str]] = {}

    for task in completed:
        try:
            client = task.client.name if task.client else "General"
        except Exception:
            client = "General"
        by_client.setdefault(client, []).append(f"✅ {task.title}")

    for task in worked_on:
        try:
            client = task.client.name if task.client else "General"
        except Exception:
            client = "General"
        by_client.setdefault(client, []).append(f"🔄 {task.title}")

    for client, tasks in sorted(by_client.items()):
        lines.append(f"**{client}**")
        for t in tasks:
            lines.append(f"- {t}")
        lines.append("")

    return {
        "text": "\n".join(lines).strip(),
        "completed_count": len(completed),
        "worked_on_count": len(worked_on),
    }


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-parse an existing daily update with AI."""
    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")

    # Ownership check: only owner or admin
    if daily.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Solo puedes re-parsear tus propios dailys")

    try:
        parsed = await parse_daily_update(daily.raw_text)
    except Exception:
        logger.exception("Unexpected error reparsing daily_id=%s", daily_id)
        raise HTTPException(status_code=502, detail="Error al re-parsear el daily")

    if daily.parsed_data != parsed:
        daily.status = DailyUpdateStatus.draft
    daily.parsed_data = parsed
    await db.commit()
    await safe_refresh(db, daily, log_context="dailys")

    return _to_response(daily)


@router.put("/{daily_id}", response_model=DailyUpdateResponse)
async def edit_daily(
    daily_id: int,
    body: DailyEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a daily update's text or parsed data (only drafts)."""
    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")

    if daily.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Solo puedes editar tus propios dailys")

    if daily.status != DailyUpdateStatus.draft:
        raise HTTPException(status_code=409, detail="Solo se pueden editar dailys en borrador")

    if body.raw_text is not None:
        daily.raw_text = body.raw_text
    if body.parsed_data is not None:
        daily.parsed_data = body.parsed_data.model_dump()
    elif body.raw_text is not None:
        # Re-parse automatically when raw_text changes and no explicit parsed_data
        try:
            parsed = await parse_daily_update(body.raw_text)
            daily.parsed_data = parsed
        except Exception:
            daily.parsed_data = None
            logger.warning("Auto-reparse failed for daily_id=%s; raw draft retained", daily_id)

    await db.commit()
    await safe_refresh(db, daily, log_context="dailys")

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


@router.post("/{daily_id}/send-discord", response_model=DeliveryReceipt, status_code=202)
async def send_daily_to_discord(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist an intent; the durable worker is the only daily sender."""
    from backend.services import deliveries
    row = await deliveries.enqueue(db, "daily", daily_id, current_user)
    source = await deliveries.authorize_source(db, "daily", daily_id, current_user)
    return await deliveries.receipt(db, row, source)


@router.delete("/{daily_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_daily(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a daily update (only owner or admin)."""
    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")

    if daily.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Solo puedes borrar tus propios dailys")

    await db.delete(daily)
    await db.commit()
