from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import DailyUpdate, DailyUpdateStatus, DiscordSettings, User
from backend.api.deps import get_current_user
from backend.config import settings
from backend.core.rate_limiter import ai_limiter
from backend.schemas.daily import (
    DailySubmitRequest,
    DailyUpdateResponse,
    DailyDiscordResponse,
    ParsedDailyData,
)
from backend.services.daily_parser import parse_daily_update, format_daily_for_discord

router = APIRouter(prefix="/api/dailys", tags=["daily-updates"])
logger = logging.getLogger(__name__)


def _to_response(d: DailyUpdate) -> DailyUpdateResponse:
    parsed = None
    if d.parsed_data:
        try:
            parsed = ParsedDailyData(**d.parsed_data)
        except Exception:
            parsed = None

    return DailyUpdateResponse(
        id=d.id,
        user_id=d.user_id,
        user_name=d.user.full_name if d.user else None,
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

    update_date = body.date or date_type.today()

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

    # Parse with AI
    try:
        parsed = await parse_daily_update(body.raw_text)
    except ValueError:
        raise HTTPException(status_code=502, detail="No se pudo interpretar el daily")
    except Exception:
        logger.exception("Unexpected error parsing daily for user_id=%s", current_user.id)
        raise HTTPException(status_code=502, detail="Error al parsear el daily")

    daily = DailyUpdate(
        user_id=current_user.id,
        date=update_date,
        raw_text=body.raw_text,
        parsed_data=parsed,
        status=DailyUpdateStatus.draft,
    )
    db.add(daily)
    await db.commit()
    await db.refresh(daily)

    # Auto-generate time entries from parsed data
    time_entries_created = 0
    if parsed:
        try:
            from backend.services.daily_timesheet import create_time_entries_from_daily
            time_entries_created = await create_time_entries_from_daily(
                db, current_user.id, update_date, parsed,
            )
            if time_entries_created:
                await db.commit()
        except Exception:
            logger.exception("Error creating time entries from daily_id=%s", daily.id)

    resp = _to_response(daily)
    resp.time_entries_created = time_entries_created
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
    q = select(DailyUpdate).order_by(DailyUpdate.date.desc(), DailyUpdate.created_at.desc())

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
    from sqlalchemy import func, or_

    today = date_type.today()

    # Tasks completed today by this user
    completed_result = await db.execute(
        select(Task)
        .where(
            Task.assigned_to == current_user.id,
            Task.status == TaskStatus.completed,
            func.date(Task.updated_at) == today,
        )
    )
    completed = completed_result.scalars().all()

    # Tasks with time entries today by this user
    te_result = await db.execute(
        select(Task)
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .where(
            TimeEntry.user_id == current_user.id,
            TimeEntry.date == today,
            Task.status != TaskStatus.completed,
        )
        .distinct()
    )
    worked_on = te_result.scalars().all()

    # Build prefill text grouped by client
    lines: list[str] = []
    by_client: dict[str, list[str]] = {}

    for task in completed:
        client = task.client.name if task.client else "General"
        by_client.setdefault(client, []).append(f"✅ {task.title}")

    for task in worked_on:
        client = task.client.name if task.client else "General"
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

    daily.parsed_data = parsed
    await db.commit()
    await db.refresh(daily)

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
    except Exception:
        pass
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
        json={"content": header},
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
        return False
    thread_id = thread_resp.json().get("id")
    if not thread_id:
        return False

    # Step 3: Send body inside the thread via webhook
    # Discord messages max 2000 chars — split if needed
    if len(body) > 2000:
        body = body[:1997] + "..."
    resp = await http.post(
        f"{webhook_url}?wait=true&thread_id={thread_id}",
        json={"content": body},
    )
    return resp.status_code in (200, 201)


@router.post("/{daily_id}/send-discord", response_model=DailyDiscordResponse)
async def send_daily_to_discord(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a parsed daily update to Discord, as a thread if bot_token is configured."""
    import httpx

    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")

    # Ownership check: only owner or admin
    if daily.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Solo puedes enviar tus propios dailys a Discord")

    if not daily.parsed_data:
        raise HTTPException(status_code=400, detail="El daily no tiene datos parseados")

    # Get Discord settings
    ds_result = await db.execute(select(DiscordSettings).limit(1))
    ds = ds_result.scalar_one_or_none()
    webhook_url = (ds.webhook_url if ds else None) or settings.DISCORD_WEBHOOK_URL

    if not webhook_url:
        raise HTTPException(status_code=400, detail="Discord webhook no configurado. Configúralo en Ajustes > Discord.")

    # Format message
    user_name = daily.user.full_name if daily.user else "Unknown"
    date_str = daily.date.isoformat()
    message = format_daily_for_discord(daily.parsed_data, user_name, date_str)

    success = False
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            bot_token = ds.bot_token if ds else None

            if bot_token:
                # Thread mode: resolve channel_id, then send as thread
                channel_id = await _resolve_channel_id(ds, webhook_url, http)
                if channel_id:
                    header = f"📋 **Daily Update — {user_name}** ({date_str})"
                    success = await _send_daily_as_thread(
                        webhook_url, bot_token, channel_id, header, message, http
                    )
                    if success and ds.channel_id:
                        # Persist cached channel_id
                        await db.commit()

            if not success:
                # Fallback: send as regular message (no thread)
                resp = await http.post(webhook_url, json={"content": message})
                success = resp.status_code in (200, 204)
    except Exception as exc:
        logger.error("Error sending daily to Discord: %s", exc)
        success = False

    if success:
        daily.status = DailyUpdateStatus.sent
        daily.discord_sent_at = datetime.now(timezone.utc)
        await db.commit()
        return DailyDiscordResponse(success=True, message="Daily enviado a Discord")
    else:
        return DailyDiscordResponse(success=False, message="Error al enviar a Discord")


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
