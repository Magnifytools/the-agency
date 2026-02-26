from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Tax, User
from backend.schemas.tax import TaxCreate, TaxUpdate, TaxResponse
from backend.services.tax_service import calculate_all_taxes, get_fiscal_deadlines
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/taxes", tags=["finance-taxes"])


@router.get("", response_model=list[TaxResponse])
async def list_taxes(
    year: Optional[int] = None,
    model: Optional[str] = None,
    period: Optional[str] = None,
    tax_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    q = select(Tax)
    if year:
        q = q.where(Tax.year == year)
    if model:
        q = q.where(Tax.model == model)
    if period:
        q = q.where(Tax.period == period)
    if tax_status:
        q = q.where(Tax.status == tax_status)
    q = q.order_by(Tax.year.desc(), Tax.due_date)
    r = await db.execute(q)
    return [TaxResponse.model_validate(t) for t in r.scalars().all()]


@router.get("/calendar")
async def tax_calendar(
    year: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    deadlines = get_fiscal_deadlines(year)
    r = await db.execute(select(Tax).where(Tax.year == year))
    taxes = r.scalars().all()
    tax_map = {(t.model, t.period): t for t in taxes}
    result = []
    for d in deadlines:
        t = tax_map.get((d["model"], d["period"]))
        result.append({
            **d,
            "year": year,
            "status": t.status if t else "sin_calcular",
            "tax_amount": t.tax_amount if t else None,
            "tax_id": t.id if t else None,
        })
    return result


@router.get("/summary/{year}")
async def tax_summary(
    year: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    r = await db.execute(select(Tax).where(Tax.year == year))
    taxes = r.scalars().all()
    total_pending = sum(t.tax_amount for t in taxes if t.status == "pendiente")
    total_paid = sum(t.tax_amount for t in taxes if t.status == "pagado")
    by_model: dict = {}
    for t in taxes:
        if t.model not in by_model:
            by_model[t.model] = {"total": 0, "pendiente": 0, "pagado": 0}
        by_model[t.model]["total"] += t.tax_amount
        by_model[t.model][t.status] = by_model[t.model].get(t.status, 0) + t.tax_amount
    return {
        "year": year,
        "total_pending": round(total_pending, 2),
        "total_paid": round(total_paid, 2),
        "total": round(total_pending + total_paid, 2),
        "by_model": by_model,
        "count": len(taxes),
    }


@router.post("/calculate/{year}")
async def calculate_taxes(
    year: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes", write=True)),
):
    results = await calculate_all_taxes(db, year)
    return {"calculated": len(results), "year": year}


@router.get("/{tax_id}", response_model=TaxResponse)
async def get_tax(
    tax_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    r = await db.execute(select(Tax).where(Tax.id == tax_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Impuesto no encontrado")
    return TaxResponse.model_validate(item)


@router.post("", response_model=TaxResponse, status_code=status.HTTP_201_CREATED)
async def create_tax(
    data: TaxCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes", write=True)),
):
    item = Tax(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return TaxResponse.model_validate(item)


@router.put("/{tax_id}", response_model=TaxResponse)
async def update_tax(
    tax_id: int,
    data: TaxUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes", write=True)),
):
    r = await db.execute(select(Tax).where(Tax.id == tax_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Impuesto no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return TaxResponse.model_validate(item)


@router.delete("/{tax_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tax(
    tax_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes", write=True)),
):
    r = await db.execute(select(Tax).where(Tax.id == tax_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Impuesto no encontrado")
    await db.delete(item)
    await db.commit()
