from __future__ import annotations
from typing import Optional

import logging
import re
from datetime import date as date_type, datetime, time, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_RE = re.compile(
    r"^https://(discord\.com|discordapp\.com)/api/webhooks/\d+/.+$"
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, DiscordSettings
from backend.api.deps import require_admin, require_module
from backend.services.discord import generate_daily_summary
from backend.schemas.delivery import DeliveryReceipt, DigestDeliveryRequest, ManualDeliveryReceipt
from backend.services.manual_communications import enqueue_request
from backend.services.temporal import business_today
from backend.services.weekly_report_service import generate_weekly_report
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
        d = datetime.now(timezone.utc).replace(tzinfo=None)
    summary = await generate_daily_summary(db, d)
    return {"summary": summary, "date": d.strftime("%Y-%m-%d")}


async def _queue_daily_summary(db, actor, day):
    day = day or business_today()
    summary = await generate_daily_summary(db, datetime.combine(day, time.min))
    receipt = await enqueue_request(db, actor, kind="daily_summary", scope="team", period_start=day,
                                   period_end=day, title=f"Resumen del día — {day.isoformat()}", content=summary)
    return dict(receipt, ok=receipt["success"], date=day.isoformat())


@router.post("/send", response_model=ManualDeliveryReceipt, status_code=202)
async def send_summary(date: date_type | None = Query(None), db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_admin)):
    return await _queue_daily_summary(db, current_user, date)


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


@router.post("/test-webhook", response_model=ManualDeliveryReceipt, status_code=202)
async def test_webhook(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin),
                       request_key: str | None = Header(None, alias="X-Agency-Request-Key", min_length=16, max_length=80)):
    day = business_today()
    return await enqueue_request(db, current_user, kind="connection_test", scope="team", period_start=day,
                                 period_end=day, title="Prueba manual de Discord",
                                 content="The Agency: prueba de conexión solicitada desde Ajustes.", intent_key=request_key)


@router.post("/send-daily-summary", response_model=ManualDeliveryReceipt, status_code=202)
async def send_daily_summary(date: date_type | None = Query(None), db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(require_admin)):
    return await _queue_daily_summary(db, current_user, date)


# ── Send custom content to Discord ─────────────────────────


@router.post("/send-custom", response_model=ManualDeliveryReceipt, status_code=202)
async def send_custom_to_discord(
    body: DiscordSendCustomRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    send_intent: str | None = Header(None, alias="X-Agency-Send-Intent"),
):
    # Protocol version, not authorization: cached digest clients used this route.
    if send_intent != "custom-v1":
        raise HTTPException(409, "Recarga la aplicación antes de enviar. Los resúmenes se envían desde su propio editor.")
    day = business_today()
    return await enqueue_request(db, current_user, kind="custom", scope="team", period_start=day,
                                 period_end=day, title="Mensaje personalizado", content=body.content)


# ── Send digest to Discord ────────────────────────────────


@router.post("/send-digest/{digest_id}", response_model=DeliveryReceipt, status_code=202)
async def send_digest_to_discord(
    digest_id: int,
    body: DigestDeliveryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    from backend.services import deliveries
    row = await deliveries.enqueue(db, "digest", digest_id, current_user, custom_content=body.content if body else None)
    source = await deliveries.authorize_source(db, "digest", digest_id, current_user)
    return await deliveries.receipt(db, row, source)


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


@router.post("/send-weekly-report", response_model=ManualDeliveryReceipt, status_code=202)
async def send_weekly_report(week_start: date_type | None = Query(None), db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(require_admin)):
    today = business_today()
    ws = week_start or today - timedelta(days=today.weekday())
    if ws.weekday() != 0:
        raise HTTPException(422, "El inicio de semana debe ser un lunes")
    we = ws + timedelta(days=6)
    report = await generate_weekly_report(db, period_start=ws, period_end=we)
    return await enqueue_request(db, current_user, kind="weekly_report", scope="team", period_start=ws,
                                 period_end=we, title=f"Informe semanal — {ws} a {we}", content=report)
