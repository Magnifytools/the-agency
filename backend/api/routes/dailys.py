from __future__ import annotations

from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import DailyUpdate, DailyUpdateStatus, DiscordSettings, User
from backend.api.deps import get_current_user
from backend.core.rate_limiter import ai_limiter
from backend.schemas.daily import (
    DailySubmitRequest,
    DailyUpdateResponse,
    DailyDiscordResponse,
    ParsedDailyData,
)
from backend.services.daily_parser import parse_daily_update, format_daily_for_discord

router = APIRouter(prefix="/api/dailys", tags=["daily-updates"])


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

    # Parse with AI
    try:
        parsed = await parse_daily_update(body.raw_text)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al parsear el daily: {str(e)}")

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

    return _to_response(daily)


@router.get("", response_model=list[DailyUpdateResponse])
async def list_dailys(
    user_id: int | None = Query(None),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List daily updates with optional filters."""
    q = select(DailyUpdate).order_by(DailyUpdate.date.desc(), DailyUpdate.created_at.desc())

    if user_id:
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


@router.get("/{daily_id}", response_model=DailyUpdateResponse)
async def get_daily(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Get a single daily update."""
    result = await db.execute(select(DailyUpdate).where(DailyUpdate.id == daily_id))
    daily = result.scalars().first()
    if not daily:
        raise HTTPException(status_code=404, detail="Daily update no encontrado")
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
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al re-parsear: {str(e)}")

    daily.parsed_data = parsed
    await db.commit()
    await db.refresh(daily)

    return _to_response(daily)


@router.post("/{daily_id}/send-discord", response_model=DailyDiscordResponse)
async def send_daily_to_discord(
    daily_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a parsed daily update to Discord."""
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

    # Get Discord webhook from settings
    ds_result = await db.execute(select(DiscordSettings).limit(1))
    ds = ds_result.scalar_one_or_none()
    webhook_url = ds.webhook_url if ds else None

    if not webhook_url:
        raise HTTPException(status_code=400, detail="Discord webhook no configurado")

    # Format message
    user_name = daily.user.full_name if daily.user else "Unknown"
    date_str = daily.date.isoformat()
    message = format_daily_for_discord(daily.parsed_data, user_name, date_str)

    # Send
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"content": message})
            success = resp.status_code in (200, 204)
    except Exception:
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
