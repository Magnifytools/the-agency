from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, WeeklyDigest, DiscordSettings
from backend.api.deps import require_admin
from backend.services.discord import generate_daily_summary, send_to_discord
from backend.services.digest_renderer import render_discord
from backend.schemas.digest import DigestContent
from backend.schemas.discord import (
    DiscordSettingsResponse,
    DiscordSettingsUpdate,
    DiscordTestResponse,
    DiscordSendResponse,
)
from backend.config import settings

router = APIRouter(prefix="/api/discord", tags=["discord"])


# ── Helpers ────────────────────────────────────────────────


async def _get_or_create_settings(db: AsyncSession) -> DiscordSettings:
    """Get the single DiscordSettings row, creating one if it doesn't exist."""
    result = await db.execute(select(DiscordSettings).limit(1))
    ds = result.scalar_one_or_none()
    if ds is None:
        ds = DiscordSettings(webhook_url=settings.DISCORD_WEBHOOK_URL or "")
        db.add(ds)
        await db.commit()
        await db.refresh(ds)
    return ds


def _settings_to_response(ds: DiscordSettings) -> DiscordSettingsResponse:
    url = ds.webhook_url or ""
    return DiscordSettingsResponse(
        id=ds.id,
        webhook_url=url,
        webhook_configured=bool(url.strip()),
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
        ds.webhook_url = payload.webhook_url
    if payload.auto_daily_summary is not None:
        ds.auto_daily_summary = payload.auto_daily_summary
    if payload.summary_time is not None:
        ds.summary_time = payload.summary_time
    if payload.include_ai_note is not None:
        ds.include_ai_note = payload.include_ai_note

    await db.commit()
    await db.refresh(ds)
    return _settings_to_response(ds)


# ── Test webhook ──────────────────────────────────────────


@router.post("/test-webhook", response_model=DiscordTestResponse)
async def test_webhook(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Send a test message to the configured Discord webhook."""
    ds = await _get_or_create_settings(db)
    url = ds.webhook_url or settings.DISCORD_WEBHOOK_URL or ""

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
    url = ds.webhook_url or settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        raise HTTPException(status_code=400, detail="No hay webhook configurado")

    if date:
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        d = datetime.now(timezone.utc)

    summary = await generate_daily_summary(db, d)
    success = await _send_discord_message(url, summary)

    if success:
        ds.last_sent_at = datetime.now(timezone.utc)
        await db.commit()
        return DiscordSendResponse(
            success=True,
            message="Resumen diario enviado a Discord",
            date=d.strftime("%Y-%m-%d"),
        )

    raise HTTPException(status_code=500, detail="Error al enviar a Discord")


# ── Send digest to Discord ────────────────────────────────


@router.post("/send-digest/{digest_id}", response_model=DiscordSendResponse)
async def send_digest_to_discord(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Send a specific digest rendered as Discord markdown to the webhook."""
    ds = await _get_or_create_settings(db)
    url = ds.webhook_url or settings.DISCORD_WEBHOOK_URL or ""

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

    raise HTTPException(status_code=500, detail="Error al enviar a Discord")
