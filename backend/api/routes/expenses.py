from __future__ import annotations

from typing import Optional
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthrange

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Expense, User
from backend.schemas.expense import ExpenseCreate, ExpenseUpdate, ExpenseResponse
from backend.api.deps import require_module
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/finance/expenses", tags=["finance-expenses"])


def _round_money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _expense_response(item: Expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=item.id,
        date=item.date,
        description=item.description,
        amount=item.amount,
        category_id=item.category_id,
        category_name=item.category.name if item.category else None,
        is_recurring=item.is_recurring,
        recurrence_period=item.recurrence_period,
        vat_rate=item.vat_rate,
        vat_amount=item.vat_amount,
        tax_regime=item.tax_regime or "standard",
        irpf_withholding_rate=float(item.irpf_withholding_rate or 0),
        irpf_withholding_amount=float(item.irpf_withholding_amount or 0),
        is_deductible=item.is_deductible,
        supplier=item.supplier,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[ExpenseResponse])
async def list_expenses(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    category_id: Optional[int] = Query(None),
    is_recurring: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    q = select(Expense).options(selectinload(Expense.category))
    if date_from:
        q = q.where(Expense.date >= date_from)
    if date_to:
        q = q.where(Expense.date <= date_to)
    if category_id:
        q = q.where(Expense.category_id == category_id)
    if is_recurring is not None:
        q = q.where(Expense.is_recurring.is_(is_recurring))
    q = q.order_by(Expense.date.desc()).limit(limit).offset(offset)
    r = await db.execute(q)
    return [_expense_response(i) for i in r.scalars().all()]


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    r = await db.execute(select(Expense).options(selectinload(Expense.category)).where(Expense.id == expense_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return _expense_response(item)


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_expense(
    data: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses", write=True)),
):
    payload = data.model_dump()
    payload["amount"] = _round_money(payload.get("amount")) or 0.0
    payload["vat_amount"] = _round_money(payload.get("vat_amount")) or 0.0
    payload["irpf_withholding_amount"] = _round_money(payload.get("irpf_withholding_amount")) or 0.0
    item = Expense(**payload)
    db.add(item)
    await db.commit()
    await safe_refresh(db, item, log_context="expenses")
    return _expense_response(item)


@router.put("/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: int,
    data: ExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses", write=True)),
):
    r = await db.execute(select(Expense).where(Expense.id == expense_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"amount", "vat_amount", "irpf_withholding_amount"}:
            value = _round_money(value)
        setattr(item, key, value)
    await db.commit()
    await safe_refresh(db, item, log_context="expenses")
    return _expense_response(item)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses", write=True)),
):
    r = await db.execute(select(Expense).where(Expense.id == expense_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    await db.delete(item)
    await db.commit()


@router.post("/generate-recurring", status_code=status.HTTP_200_OK)
async def generate_recurring_expenses(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses", write=True)),
):
    """Generate copies of recurring expenses for the given month (defaults to current month)."""
    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month
    _, last_day = monthrange(y, m)
    target_date = date(y, m, 1)

    # Get all recurring expenses (use first day of target month as date)
    r = await db.execute(select(Expense).where(Expense.is_recurring.is_(True)))
    templates = r.scalars().all()

    created = 0
    skipped = 0
    for tmpl in templates:
        # Check if already generated for this month (match by description + category + amount + supplier)
        existing = await db.execute(
            select(Expense).where(
                Expense.description == tmpl.description,
                Expense.category_id == tmpl.category_id,
                Expense.amount == tmpl.amount,
                Expense.supplier == tmpl.supplier,
                Expense.date >= date(y, m, 1),
                Expense.date <= date(y, m, last_day),
                Expense.id != tmpl.id,
            )
        )
        if existing.scalars().first():
            skipped += 1
            continue

        new_expense = Expense(
            date=target_date,
            description=tmpl.description,
            amount=tmpl.amount,
            category_id=tmpl.category_id,
            is_recurring=False,
            recurrence_period=tmpl.recurrence_period,
            vat_rate=tmpl.vat_rate,
            vat_amount=tmpl.vat_amount,
            tax_regime=tmpl.tax_regime,
            irpf_withholding_rate=tmpl.irpf_withholding_rate,
            irpf_withholding_amount=tmpl.irpf_withholding_amount,
            is_deductible=tmpl.is_deductible,
            supplier=tmpl.supplier,
            notes=f"[Automático] {tmpl.notes or ''}".strip(),
        )
        db.add(new_expense)
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped, "month": f"{y}-{m:02d}"}
