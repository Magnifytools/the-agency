from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Income, Expense, Tax, User
from backend.api.deps import require_module
from backend.services.csv_utils import build_csv_response
from backend.services.report_period import MAX_REPORT_YEAR, MIN_REPORT_YEAR
router = APIRouter(prefix="/api/finance/export", tags=["finance-export"])


@router.get("/income")
async def export_income(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_income")),
):
    q = select(Income)
    if year:
        q = q.where(extract("year", Income.date) == year)
    if month:
        q = q.where(extract("month", Income.date) == month)
    q = q.order_by(Income.date.desc())
    r = await db.execute(q)
    items = r.scalars().all()

    header = ["fecha", "descripcion", "importe", "tipo", "factura", "iva_tipo", "iva_importe", "estado", "notas"]
    csv_rows = (
        [
            item.date.isoformat(),
            item.description,
            item.amount,
            item.type,
            item.invoice_number,
            item.vat_rate,
            item.vat_amount,
            item.status,
            item.notes,
        ]
        for item in items
    )
    return build_csv_response("ingresos.csv", header, csv_rows)


@router.get("/expenses")
async def export_expenses(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    q = select(Expense)
    if year:
        q = q.where(extract("year", Expense.date) == year)
    if month:
        q = q.where(extract("month", Expense.date) == month)
    q = q.order_by(Expense.date.desc())
    r = await db.execute(q)
    items = r.scalars().all()

    header = ["fecha", "descripcion", "importe", "proveedor", "iva_tipo", "iva_importe", "deducible", "recurrente", "notas"]
    csv_rows = (
        [
            item.date.isoformat(),
            item.description,
            item.amount,
            item.supplier,
            item.vat_rate,
            item.vat_amount,
            item.is_deductible,
            item.is_recurring,
            item.notes,
        ]
        for item in items
    )
    return build_csv_response("gastos.csv", header, csv_rows)


@router.get("/taxes")
async def export_taxes(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    q = select(Tax)
    if year:
        q = q.where(Tax.year == year)
    q = q.order_by(Tax.year.desc(), Tax.due_date)
    r = await db.execute(q)
    items = r.scalars().all()

    header = ["nombre", "modelo", "periodo", "ano", "base", "tipo", "cuota", "estado", "vencimiento", "pagado"]
    csv_rows = (
        [
            item.name,
            item.model,
            item.period,
            item.year,
            item.base_amount,
            item.tax_rate,
            item.tax_amount,
            item.status,
            item.due_date.isoformat() if item.due_date else "",
            item.paid_date.isoformat() if item.paid_date else "",
        ]
        for item in items
    )
    return build_csv_response("impuestos.csv", header, csv_rows)
