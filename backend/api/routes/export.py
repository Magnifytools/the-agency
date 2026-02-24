from __future__ import annotations

from typing import Optional
from datetime import date
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Income, Expense, Tax, User
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/export", tags=["finance-export"])


@router.get("/income")
async def export_income(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["fecha", "descripcion", "importe", "tipo", "factura", "iva_tipo", "iva_importe", "estado", "notas"])
    for item in items:
        writer.writerow([
            item.date.isoformat(), item.description, item.amount, item.type,
            item.invoice_number, item.vat_rate, item.vat_amount, item.status, item.notes,
        ])

    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ingresos.csv"},
    )


@router.get("/expenses")
async def export_expenses(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["fecha", "descripcion", "importe", "proveedor", "iva_tipo", "iva_importe", "deducible", "recurrente", "notas"])
    for item in items:
        writer.writerow([
            item.date.isoformat(), item.description, item.amount, item.supplier,
            item.vat_rate, item.vat_amount, item.is_deductible, item.is_recurring, item.notes,
        ])

    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gastos.csv"},
    )


@router.get("/taxes")
async def export_taxes(
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_taxes")),
):
    q = select(Tax)
    if year:
        q = q.where(Tax.year == year)
    q = q.order_by(Tax.year.desc(), Tax.due_date)
    r = await db.execute(q)
    items = r.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["nombre", "modelo", "periodo", "ano", "base", "tipo", "cuota", "estado", "vencimiento", "pagado"])
    for item in items:
        writer.writerow([
            item.name, item.model, item.period, item.year, item.base_amount,
            item.tax_rate, item.tax_amount, item.status,
            item.due_date.isoformat() if item.due_date else "",
            item.paid_date.isoformat() if item.paid_date else "",
        ])

    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=impuestos.csv"},
    )
