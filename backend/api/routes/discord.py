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
    # Legacy plaintext rejected — must be encrypted via migration or settings update
    logger.warning("Rejecting plaintext Discord field — run encrypt_discord_secrets migration")
    return ""


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
        d = datetime.now(timezone.utc)
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
        d = datetime.now(timezone.utc)

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
        d = datetime.now(timezone.utc)

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
            ds.last_sent_at = datetime.now(timezone.utc)
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
            ds.last_sent_at = datetime.now(timezone.utc)
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
        ds.last_sent_at = datetime.now(timezone.utc)
        await db.commit()
        return DiscordSendResponse(
            success=True,
            message=f"Digest #{digest_id} enviado a Discord",
        )

    return DiscordSendResponse(
        success=False,
        message=f"Error al enviar digest #{digest_id} a Discord. Verifica el webhook.",
    )
