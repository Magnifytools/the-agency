from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Forecast, User
from backend.schemas.forecast import ForecastCreate, ForecastUpdate, ForecastResponse
from backend.services.forecast_service import generate_forecasts, calculate_runway, get_vs_actual
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/forecasts", tags=["finance-forecasts"])


@router.get("", response_model=list[ForecastResponse])
async def list_forecasts(
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    q = select(Forecast)
    if year:
        q = q.where(extract("year", Forecast.month) == year)
    q = q.order_by(Forecast.month)
    r = await db.execute(q)
    return [ForecastResponse.model_validate(f) for f in r.scalars().all()]


@router.post("/generate")
async def generate(
    months: int = Query(default=6),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    results = await generate_forecasts(db, months)
    return {"generated": len(results)}


@router.get("/runway")
async def runway(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    return await calculate_runway(db)


@router.get("/vs-actual")
async def vs_actual(
    year: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    return await get_vs_actual(db, year)


@router.get("/{forecast_id}", response_model=ForecastResponse)
async def get_forecast(
    forecast_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    r = await db.execute(select(Forecast).where(Forecast.id == forecast_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Prevision no encontrada")
    return ForecastResponse.model_validate(item)


@router.post("", response_model=ForecastResponse, status_code=status.HTTP_201_CREATED)
async def create_forecast(
    data: ForecastCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    item = Forecast(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ForecastResponse.model_validate(item)


@router.put("/{forecast_id}", response_model=ForecastResponse)
async def update_forecast(
    forecast_id: int,
    data: ForecastUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    r = await db.execute(select(Forecast).where(Forecast.id == forecast_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Prevision no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return ForecastResponse.model_validate(item)


@router.delete("/{forecast_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_forecast(
    forecast_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_forecasts")),
):
    r = await db.execute(select(Forecast).where(Forecast.id == forecast_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Prevision no encontrada")
    await db.delete(item)
    await db.commit()
