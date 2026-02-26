from __future__ import annotations

from typing import Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Income, User
from backend.schemas.income import IncomeCreate, IncomeUpdate, IncomeResponse
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/income", tags=["finance-income"])


def _round_money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _income_response(item: Income) -> IncomeResponse:
    return IncomeResponse(
        id=item.id,
        date=item.date,
        description=item.description,
        amount=item.amount,
        type=item.type,
        client_id=item.client_id,
        client_name=item.client.name if item.client else None,
        invoice_number=item.invoice_number,
        vat_rate=item.vat_rate,
        vat_amount=item.vat_amount,
        status=item.status,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[IncomeResponse])
async def list_income(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    client_id: Optional[int] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income")),
):
    q = select(Income)
    if date_from:
        q = q.where(Income.date >= date_from)
    if date_to:
        q = q.where(Income.date <= date_to)
    if client_id:
        q = q.where(Income.client_id == client_id)
    if type:
        q = q.where(Income.type == type)
    if status:
        q = q.where(Income.status == status)
    q = q.order_by(Income.date.desc())
    r = await db.execute(q)
    return [_income_response(i) for i in r.scalars().all()]


@router.get("/{income_id}", response_model=IncomeResponse)
async def get_income(
    income_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income")),
):
    r = await db.execute(select(Income).where(Income.id == income_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    return _income_response(item)


@router.post("", response_model=IncomeResponse, status_code=status.HTTP_201_CREATED)
async def create_income(
    data: IncomeCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income", write=True)),
):
    payload = data.model_dump()
    payload["amount"] = _round_money(payload.get("amount")) or 0.0
    payload["vat_amount"] = _round_money(payload.get("vat_amount")) or 0.0
    item = Income(**payload)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _income_response(item)


@router.put("/{income_id}", response_model=IncomeResponse)
async def update_income(
    income_id: int,
    data: IncomeUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income", write=True)),
):
    r = await db.execute(select(Income).where(Income.id == income_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"amount", "vat_amount"}:
            value = _round_money(value)
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return _income_response(item)


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_income(
    income_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income", write=True)),
):
    r = await db.execute(select(Income).where(Income.id == income_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    await db.delete(item)
    await db.commit()
