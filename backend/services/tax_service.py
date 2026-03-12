from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, extract, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Tax, Income, Expense, ExpenseCategory, FinancialSettings


async def _get_setting_float(db: AsyncSession, field: str, default: float) -> float:
    r = await db.execute(select(FinancialSettings))
    settings = r.scalars().first()
    if settings is None:
        return default
    return getattr(settings, field, default)


def _quarter_months(quarter: int) -> tuple[int, int]:
    start = (quarter - 1) * 3 + 1
    return start, start + 2


async def _income_vat_for_quarter(db: AsyncSession, year: int, quarter: int) -> tuple[float, float]:
    """Return (vat_total, base_total) for income in the quarter."""
    m_start, m_end = _quarter_months(quarter)
    r = await db.execute(
        select(Income).where(
            extract("year", Income.date) == year,
            extract("month", Income.date) >= m_start,
            extract("month", Income.date) <= m_end,
        )
    )
    rows = r.scalars().all()
    vat_total = Decimal("0")
    base_total = Decimal("0")
    for row in rows:
        base_total += Decimal(str(row.amount or 0))
        if row.vat_amount is not None:
            vat_total += Decimal(str(row.vat_amount))
        else:
            vat_total += Decimal(str(row.amount or 0)) * Decimal(str(row.vat_rate or 0)) / Decimal("100")
    return (
        float(vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        float(base_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    )


async def _expense_vat_for_quarter(db: AsyncSession, year: int, quarter: int) -> tuple[float, float]:
    """Return (vat_total, base_total) for deductible expenses in the quarter."""
    m_start, m_end = _quarter_months(quarter)
    r = await db.execute(
        select(Expense).where(
            extract("year", Expense.date) == year,
            extract("month", Expense.date) >= m_start,
            extract("month", Expense.date) <= m_end,
            Expense.is_deductible.is_(True),
        )
    )
    rows = r.scalars().all()
    vat_total = Decimal("0")
    base_total = Decimal("0")
    for row in rows:
        base_total += Decimal(str(row.amount or 0))
        if row.vat_amount is not None:
            vat_total += Decimal(str(row.vat_amount))
        else:
            vat_total += Decimal(str(row.amount or 0)) * Decimal(str(row.vat_rate or 0)) / Decimal("100")
    return (
        float(vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        float(base_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    )


async def calculate_iva_quarterly(db: AsyncSession, year: int, quarter: int) -> dict:
    repercutido, income_base = await _income_vat_for_quarter(db, year, quarter)
    soportado, _expense_base = await _expense_vat_for_quarter(db, year, quarter)
    cuota = repercutido - soportado
    vat_rate = await _get_setting_float(db, "default_vat_rate", 21.0)
    return {
        "name": f"IVA Trimestral Q{quarter}",
        "model": "303",
        "period": f"Q{quarter}",
        "year": year,
        "base_amount": round(income_base, 2),  # base imponible (ingresos sin IVA)
        "tax_rate": vat_rate,
        "tax_amount": round(cuota, 2),
    }


async def calculate_corporate_tax(db: AsyncSession, year: int) -> dict:
    r = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(extract("year", Income.date) == year)
    )
    total_income = Decimal(str(r.scalar()))
    r = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(extract("year", Expense.date) == year)
    )
    total_expenses = Decimal(str(r.scalar()))
    profit = total_income - total_expenses
    rate = Decimal(str(await _get_setting_float(db, "corporate_tax_rate", 25.0)))
    tax = max(profit * rate / Decimal("100"), Decimal("0"))
    return {
        "name": "Impuesto de Sociedades",
        "model": "200",
        "period": "anual",
        "year": year,
        "base_amount": float(profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "tax_rate": float(rate),
        "tax_amount": float(tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }


async def calculate_irpf_quarterly(db: AsyncSession, year: int, quarter: int) -> dict:
    m_start, m_end = _quarter_months(quarter)
    r = await db.execute(
        select(ExpenseCategory).where(ExpenseCategory.name == "Servicios profesionales")
    )
    cat = r.scalars().first()
    base = Decimal("0")
    if cat:
        r = await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                extract("year", Expense.date) == year,
                extract("month", Expense.date) >= m_start,
                extract("month", Expense.date) <= m_end,
                Expense.category_id == cat.id,
            )
        )
        base = Decimal(str(r.scalar()))
    rate = Decimal(str(await _get_setting_float(db, "irpf_retention_rate", 15.0)))
    tax = base * rate / Decimal("100")
    return {
        "name": f"Retenciones IRPF Q{quarter}",
        "model": "111",
        "period": f"Q{quarter}",
        "year": year,
        "base_amount": float(base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "tax_rate": float(rate),
        "tax_amount": float(tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }


def get_fiscal_deadlines(year: int) -> list[dict]:
    return [
        {"model": "303", "period": "Q1", "due_date": f"{year}-04-20", "description": "IVA 1T"},
        {"model": "303", "period": "Q2", "due_date": f"{year}-07-20", "description": "IVA 2T"},
        {"model": "303", "period": "Q3", "due_date": f"{year}-10-20", "description": "IVA 3T"},
        {"model": "303", "period": "Q4", "due_date": f"{year + 1}-01-20", "description": "IVA 4T"},
        {"model": "111", "period": "Q1", "due_date": f"{year}-04-20", "description": "IRPF 1T"},
        {"model": "111", "period": "Q2", "due_date": f"{year}-07-20", "description": "IRPF 2T"},
        {"model": "111", "period": "Q3", "due_date": f"{year}-10-20", "description": "IRPF 3T"},
        {"model": "111", "period": "Q4", "due_date": f"{year + 1}-01-20", "description": "IRPF 4T"},
        {"model": "200", "period": "anual", "due_date": f"{year + 1}-07-25", "description": "Impuesto Sociedades"},
    ]


def _due_date_for(model: str, period: str, year: int) -> Optional[date]:
    for d in get_fiscal_deadlines(year):
        if d["model"] == model and d["period"] == period:
            return date.fromisoformat(d["due_date"])
    return None


async def _upsert_tax(db: AsyncSession, data: dict) -> Tax:
    r = await db.execute(
        select(Tax).where(
            Tax.model == data["model"],
            Tax.period == data["period"],
            Tax.year == data["year"],
        )
    )
    existing = r.scalars().first()
    due = _due_date_for(data["model"], data["period"], data["year"])
    if existing:
        existing.name = data["name"]
        existing.base_amount = data["base_amount"]
        existing.tax_rate = data["tax_rate"]
        existing.tax_amount = data["tax_amount"]
        if due:
            existing.due_date = due
        return existing
    else:
        tax = Tax(
            name=data["name"],
            model=data["model"],
            period=data["period"],
            year=data["year"],
            base_amount=data["base_amount"],
            tax_rate=data["tax_rate"],
            tax_amount=data["tax_amount"],
            due_date=due,
            status="pendiente",
        )
        db.add(tax)
        return tax


async def calculate_all_taxes(db: AsyncSession, year: int) -> list[Tax]:
    results = []
    for q in range(1, 5):
        iva = await calculate_iva_quarterly(db, year, q)
        results.append(await _upsert_tax(db, iva))
        irpf = await calculate_irpf_quarterly(db, year, q)
        results.append(await _upsert_tax(db, irpf))
    corp = await calculate_corporate_tax(db, year)
    results.append(await _upsert_tax(db, corp))
    await db.commit()
    for r in results:
        await db.refresh(r)
    return results
