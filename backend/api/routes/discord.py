from __future__ import annotations
from typing import Optional

import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_RE = re.compile(
    r"^https://(discord\.com|discordapp\.com)/api/webhooks/\d+/.+$"
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, WeeklyDigest, DiscordSettings
from backend.api.deps import require_admin, require_module
from backend.services.discord import generate_daily_summary, send_to_discord
from backend.api.routes.dailys import _resolve_channel_id, _send_daily_as_thread
from backend.services.digest_renderer import render_discord
from backend.schemas.digest import DigestContent
from backend.core.security import encrypt_vault_secret, decrypt_vault_secret
from backend.api.middleware.audit_log import log_audit
from backend.schemas.discord import (
    DiscordSettingsResponse,
    DiscordSettingsUpdate,
    DiscordTestResponse,
    DiscordSendResponse,
    DiscordSendCustomRequest,
)
from backend.config import settings
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/discord", tags=["discord"])


# ── Helpers ────────────────────────────────────────────────


async def _get_or_create_settings(db: AsyncSession) -> DiscordSettings:
    """Get the single DiscordSettings row, creating one if it doesn't exist."""
    result = await db.execute(select(DiscordSettings).limit(1))
    ds = result.scalar_one_or_none()
    if ds is None:
        raw_url = settings.DISCORD_WEBHOOK_URL or ""
        encrypted_url = encrypt_vault_secret(raw_url) if raw_url.strip() else ""
        ds = DiscordSettings(webhook_url=encrypted_url)
        db.add(ds)
        await db.commit()
        await safe_refresh(db, ds, log_context="discord")
    return ds


def _decrypt_field(value: str | None) -> str:
    """Decrypt a vault-encrypted field. Rejects unencrypted legacy values."""
    if not value:
        return ""
    if value.startswith("v1:"):
        try:
            return decrypt_vault_secret(value)
        except Exception:
            logger.error("Failed to decrypt Discord field — value is corrupt or key changed")
            return ""
    # Legacy plaintext — accept it (will be auto-encrypted on next write/daily send)
    logger.warning("Accepting plaintext Discord field — will be auto-encrypted on next use")
    return value


def _settings_to_response(ds: DiscordSettings) -> DiscordSettingsResponse:
    url = _decrypt_field(ds.webhook_url)
    return DiscordSettingsResponse(
        id=ds.id,
        webhook_configured=bool(url.strip()),
        bot_token_configured=bool(ds.bot_token),
        auto_daily_summary=ds.auto_daily_summary,
        summary_time=ds.summary_time or "18:00",
        include_ai_note=ds.include_ai_note,
        last_sent_at=ds.last_sent_at,
    )


async def _send_discord_message(webhook_url: str, message: str) -> bool:
    """Send a message to a Discord webhook. Returns True on success."""
    if not webhook_url:
        return False
    # Discord limit is 2000 chars per message
    if len(message) > 2000:
        message = message[:1997] + "..."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"content": message})
            return resp.status_code in (200, 204)
    except (httpx.HTTPError, Exception):
        return False


# ── Existing endpoints (kept) ─────────────────────────────


@router.get("/preview")
async def preview_summary(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if date:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        d = datetime.utcnow()
    summary = await generate_daily_summary(db, d)
    return {"summary": summary, "date": d.strftime("%Y-%m-%d")}


@router.post("/send")
async def send_summary(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not settings.DISCORD_WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="DISCORD_WEBHOOK_URL no configurada")

    if date:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        d = datetime.utcnow()

    summary = await generate_daily_summary(db, d)
    success = await send_to_discord(summary)
    if not success:
        raise HTTPException(status_code=500, detail="Error al enviar a Discord")
    return {"ok": True, "date": d.strftime("%Y-%m-%d")}


# ── Settings ──────────────────────────────────────────────


@router.get("/settings", response_model=DiscordSettingsResponse)
async def get_discord_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Get Discord integration settings."""
    ds = await _get_or_create_settings(db)
    return _settings_to_response(ds)


@router.put("/settings", response_model=DiscordSettingsResponse)
async def update_discord_settings(
    payload: DiscordSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update Discord integration settings."""
    ds = await _get_or_create_settings(db)

    if payload.webhook_url is not None:
        if payload.webhook_url.strip() and not DISCORD_WEBHOOK_RE.match(payload.webhook_url):
            raise HTTPException(
                status_code=400,
                detail="URL de webhook inválida. Debe ser una URL de webhook de Discord válida.",
            )
        ds.webhook_url = encrypt_vault_secret(payload.webhook_url.strip()) if payload.webhook_url.strip() else ""
        ds.channel_id = None  # Reset cached channel_id when webhook changes
    if payload.bot_token is not None:
        raw_token = payload.bot_token.strip()
        ds.bot_token = encrypt_vault_secret(raw_token) if raw_token else None
    if payload.auto_daily_summary is not None:
        ds.auto_daily_summary = payload.auto_daily_summary
    if payload.summary_time is not None:
        ds.summary_time = payload.summary_time
    if payload.include_ai_note is not None:
        ds.include_ai_note = payload.include_ai_note

    await db.commit()
    await safe_refresh(db, ds, log_context="discord")
    log_audit(_.id, "update", "settings", "discord")
    return _settings_to_response(ds)


# ── Test webhook ──────────────────────────────────────────


@router.post("/test-webhook", response_model=DiscordTestResponse)
async def test_webhook(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Send a test message to the configured Discord webhook."""
    ds = await _get_or_create_settings(db)
    url = _decrypt_field(ds.webhook_url) or settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        raise HTTPException(status_code=400, detail="No hay webhook configurado")

    test_msg = "🧪 **Test de conexión** — Agency Manager está conectado correctamente a este canal."
    success = await _send_discord_message(url, test_msg)

    if not success:
        return DiscordTestResponse(success=False, message="Error al enviar al webhook. Verifica la URL.")
    return DiscordTestResponse(success=True, message="Mensaje de test enviado correctamente")


# ── Send daily summary ────────────────────────────────────


@router.post("/send-daily-summary", response_model=DiscordSendResponse)
async def send_daily_summary(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Generate and send the daily summary to Discord."""
    ds = await _get_or_create_settings(db)
    url = _decrypt_field(ds.webhook_url) or settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        raise HTTPException(status_code=400, detail="No hay webhook configurado")

    if date:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        d = datetime.utcnow()

    try:
        summary = await generate_daily_summary(db, d)
    except Exception as exc:
        logger.error("Error generating daily summary: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Error al generar el resumen diario")

    success = False
    bot_token = _decrypt_field(ds.bot_token) if ds else None

    if bot_token:
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                channel_id = await _resolve_channel_id(ds, url, http)
                if channel_id:
                    date_str = d.strftime("%d/%m/%Y")
                    header = f"📋 **Resumen del dia — {date_str}**"
                    # Strip the first line (header) from summary to avoid duplication
                    body_lines = summary.split("\n")
                    body = "\n".join(body_lines[1:]).strip() or summary
                    success = await _send_daily_as_thread(
                        url, bot_token, channel_id, header, body, http
                    )
                    if success and ds.channel_id:
                        await db.commit()
        except Exception as exc:
            logger.warning("Thread mode failed for summary: %s", exc)
            success = False

    if not success:
        success = await _send_discord_message(url, summary)

    if success:
        try:
            ds.last_sent_at = datetime.utcnow()
            await db.commit()
        except Exception:
            logger.warning("Discord message sent but failed to update last_sent_at")
        return DiscordSendResponse(
            success=True,
            message="Resumen diario enviado a Discord",
            date=d.strftime("%Y-%m-%d"),
        )

    return DiscordSendResponse(
        success=False,
        message="Error al enviar a Discord. Verifica el webhook.",
        date=d.strftime("%Y-%m-%d"),
    )


# ── Send custom content to Discord ─────────────────────────


@router.post("/send-custom", response_model=DiscordSendResponse)
async def send_custom_to_discord(
    body: DiscordSendCustomRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Send custom (edited) content to Discord. Used for preview-then-send flows."""
    ds = await _get_or_create_settings(db)
    url = _decrypt_field(ds.webhook_url) or settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        raise HTTPException(status_code=400, detail="No hay webhook configurado")

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="El contenido no puede estar vacío")

    success = await _send_discord_message(url, body.content.strip())

    if success:
        try:
            ds.last_sent_at = datetime.utcnow()
            await db.commit()
        except Exception:
            logger.warning("Discord message sent but failed to update last_sent_at")
        return DiscordSendResponse(
            success=True,
            message="Mensaje enviado a Discord",
        )

    return DiscordSendResponse(
        success=False,
        message="Error al enviar a Discord. Verifica el webhook.",
    )


# ── Send digest to Discord ────────────────────────────────


@router.post("/send-digest/{digest_id}", response_model=DiscordSendResponse)
async def send_digest_to_discord(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("digests", write=True)),
):
    """Send a specific digest rendered as Discord markdown to the webhook."""
    ds = await _get_or_create_settings(db)
    url = _decrypt_field(ds.webhook_url) or settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        raise HTTPException(status_code=400, detail="No hay webhook configurado")

    # Load digest
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()
    if not digest:
        raise HTTPException(status_code=404, detail="Digest no encontrado")
    if not digest.content:
        raise HTTPException(status_code=400, detail="El digest no tiene contenido")

    try:
        content = DigestContent(**digest.content)
    except Exception:
        raise HTTPException(status_code=400, detail="Contenido del digest malformado")

    rendered = render_discord(content)
    success = await _send_discord_message(url, rendered)

    if success:
        ds.last_sent_at = datetime.utcnow()
        await db.commit()
        return DiscordSendResponse(
            success=True,
            message=f"Digest #{digest_id} enviado a Discord",
        )

    return DiscordSendResponse(
        success=False,
        message=f"Error al enviar digest #{digest_id} a Discord. Verifica el webhook.",
    )


# ── Weekly Report via Discord DM ─────────────────────────────


async def _send_discord_dm(bot_token: str, user_id: str, message: str) -> bool:
    """Send a Discord DM to a specific user using the Bot API."""
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Create DM channel
            resp = await client.post(
                "https://discord.com/api/v10/users/@me/channels",
                headers=headers,
                json={"recipient_id": user_id},
            )
            if resp.status_code not in (200, 201):
                logger.error("Failed to create DM channel: %s", resp.text)
                return False
            channel_id = resp.json()["id"]

            # Send message (split if > 2000 chars)
            chunks = [message[i:i+1990] for i in range(0, len(message), 1990)]
            for chunk in chunks:
                resp = await client.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    headers=headers,
                    json={"content": chunk},
                )
                if resp.status_code not in (200, 201):
                    logger.error("Failed to send DM: %s", resp.text)
                    return False
            return True
    except Exception as exc:
        logger.error("Discord DM error: %s", exc)
        return False


@router.post("/send-weekly-report", response_model=DiscordSendResponse)
async def send_weekly_report(
    week_start: Optional[str] = Query(None, description="YYYY-MM-DD (Monday)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Generate and send a weekly timesheet report via Discord DM to the owner."""
    from datetime import date as date_type, timedelta
    from sqlalchemy.orm import selectinload

    ds = await _get_or_create_settings(db)
    bot_token = _decrypt_field(ds.bot_token) if ds else None
    owner_id = settings.DISCORD_OWNER_USER_ID

    if not bot_token:
        raise HTTPException(status_code=400, detail="Bot token no configurado en Discord settings")
    if not owner_id:
        raise HTTPException(status_code=400, detail="DISCORD_OWNER_USER_ID no configurado en variables de entorno")

    # Calculate week range
    today = datetime.utcnow().date()
    if week_start:
        ws = datetime.strptime(week_start, "%Y-%m-%d").date()
    else:
        ws = today - timedelta(days=today.weekday() + 7)  # Last week's Monday

    we = ws + timedelta(days=6)  # Sunday
    start_dt = datetime.combine(ws, datetime.min.time())
    end_dt = datetime.combine(we + timedelta(days=1), datetime.min.time())

    # Load all users
    from backend.db.models import TimeEntry, Task, Client, Project

    users_result = await db.execute(select(User).order_by(User.full_name))
    users = users_result.scalars().all()
    user_map = {u.id: u for u in users}

    # Load time entries for the week
    entries_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start_dt,
            TimeEntry.date < end_dt,
        )
    )
    entries = entries_result.scalars().all()

    # Aggregate by user and client
    user_hours: dict[int, float] = {}
    client_hours: dict[str, float] = {}
    client_cost: dict[str, float] = {}

    task_ids = {e.task_id for e in entries if e.task_id}
    tasks_map: dict[int, dict] = {}
    if task_ids:
        task_result = await db.execute(
            select(Task, Client.name.label("client_name"), Project.monthly_fee)
            .outerjoin(Client, Task.client_id == Client.id)
            .outerjoin(Project, Task.project_id == Project.id)
            .where(Task.id.in_(task_ids))
        )
        for row in task_result.all():
            tasks_map[row[0].id] = {
                "client_name": row[1] or "Sin cliente",
                "monthly_fee": row[2] or 0,
            }

    for entry in entries:
        mins = entry.minutes or 0
        uid = entry.user_id
        user_hours[uid] = user_hours.get(uid, 0) + mins / 60.0

        client_name = "Sin cliente"
        if entry.task_id and entry.task_id in tasks_map:
            client_name = tasks_map[entry.task_id]["client_name"]

        client_hours[client_name] = client_hours.get(client_name, 0) + mins / 60.0
        rate = float(user_map[uid].hourly_rate) if uid in user_map and user_map[uid].hourly_rate else float(settings.DEFAULT_HOURLY_RATE)
        client_cost[client_name] = client_cost.get(client_name, 0) + (mins / 60.0) * rate

    # Get overdue tasks
    from backend.db.models import TaskStatus
    overdue_result = await db.execute(
        select(Task)
        .outerjoin(Client, Task.client_id == Client.id)
        .where(
            Task.status.notin_([TaskStatus.completed]),
            Task.due_date < start_dt,
            Task.due_date.isnot(None),
        )
        .options(selectinload(Task.client))
        .limit(10)
    )
    overdue_tasks = overdue_result.scalars().all()

    # Build report
    total_hours = sum(user_hours.values())
    total_capacity = sum((u.weekly_hours or 40) for u in users)

    lines = [
        f"📊 **Informe Semanal — {ws.strftime('%d/%m')} al {we.strftime('%d/%m/%Y')}**",
        "",
        f"**Horas totales equipo:** {total_hours:.1f}h / {total_capacity}h ({total_hours/total_capacity*100:.0f}%)" if total_capacity else f"**Horas totales:** {total_hours:.1f}h",
        "",
    ]

    # Per-user breakdown
    lines.append("👥 **Por persona:**")
    for u in users:
        h = user_hours.get(u.id, 0)
        cap = u.weekly_hours or 40
        lines.append(f"  • {u.full_name}: {h:.1f}h / {cap}h ({h/cap*100:.0f}%)" if cap else f"  • {u.full_name}: {h:.1f}h")
    lines.append("")

    # Per-client breakdown
    lines.append("🏢 **Por cliente:**")
    sorted_clients = sorted(client_hours.items(), key=lambda x: x[1], reverse=True)
    for name, hours in sorted_clients:
        cost = client_cost.get(name, 0)
        pct = (hours / total_hours * 100) if total_hours else 0
        alert = " ⚠️" if pct > 40 else ""
        lines.append(f"  • {name}: {hours:.1f}h ({pct:.0f}%) — {cost:.0f}€{alert}")

    # Zero-activity clients
    active_clients_result = await db.execute(
        select(Client.name).where(Client.status == "active")
    )
    active_names = {r[0] for r in active_clients_result.all()}
    inactive = active_names - set(client_hours.keys())
    if inactive:
        lines.append("")
        lines.append("💤 **Sin actividad esta semana:**")
        for name in sorted(inactive):
            lines.append(f"  • {name}")

    # Overdue tasks
    if overdue_tasks:
        lines.append("")
        lines.append(f"⚠️ **{len(overdue_tasks)} tareas vencidas:**")
        for t in overdue_tasks[:5]:
            client_label = t.client.name if t.client else "Sin cliente"
            due = t.due_date.strftime("%d/%m") if t.due_date else "?"
            lines.append(f"  • [{client_label}] {t.title} (vencía {due})")
        if len(overdue_tasks) > 5:
            lines.append(f"  ... y {len(overdue_tasks) - 5} más")

    report = "\n".join(lines)

    # Send via Discord DM
    success = await _send_discord_dm(bot_token, owner_id, report)

    if success:
        return DiscordSendResponse(success=True, message="Informe semanal enviado por DM")
    return DiscordSendResponse(success=False, message="Error al enviar DM. Verifica bot_token y DISCORD_OWNER_USER_ID.")
