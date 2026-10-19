"""Festivos de empresa (Ajustes → Festivos). Leer: cualquiera; escribir: admin."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.api.utils.db_helpers import safe_refresh
from backend.db.database import get_db
from backend.db.models import CompanyHoliday, User
from backend.schemas.holiday import CompanyHolidayCreate, CompanyHolidayResponse

router = APIRouter(prefix="/api/holidays", tags=["holidays"])


@router.get("", response_model=list[CompanyHolidayResponse])
async def list_holidays(
    year: Optional[int] = Query(None),
    region: Optional[str] = Query(None, description="Filter by CCAA code"),
    include_national: bool = Query(True, description="Include national holidays"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(CompanyHoliday).order_by(CompanyHoliday.date.asc())
    if year:
        q = q.where(
            CompanyHoliday.date >= date(year, 1, 1),
            CompanyHoliday.date <= date(year, 12, 31),
        )
    if region:
        conditions = [CompanyHoliday.region == region]
        if include_national:
            conditions.append(CompanyHoliday.region.is_(None))
        q = q.where(or_(*conditions))
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=CompanyHolidayResponse, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    body: CompanyHolidayCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    holiday = CompanyHoliday(
        date=body.date, name=body.name, country=body.country,
        region=body.region, locality=body.locality,
    )
    db.add(holiday)
    await db.commit()
    await safe_refresh(db, holiday, log_context="holidays")
    return holiday


@router.delete("/{holiday_id}")
async def delete_holiday(
    holiday_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    holiday = await db.get(CompanyHoliday, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await db.delete(holiday)
    await db.commit()
    return {"ok": True}
