from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User
from backend.api.deps import require_admin
from backend.services.discord import generate_daily_summary, send_to_discord
from backend.config import settings

router = APIRouter(prefix="/api/discord", tags=["discord"])


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
