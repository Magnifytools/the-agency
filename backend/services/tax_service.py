from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, extract, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Tax, Income, Expense, ExpenseCategory, FinancialSettings


# ---------------------------------------------------------------------------
# Tax regime constants
# ---------------------------------------------------------------------------
REGIME_STANDARD = "standard"
REGIME_EU_REVERSE_CHARGE = "eu_reverse_charge"
REGIME_INTRACOMUNITARIO = "intracomunitario"
REGIME_EXPORT = "export"

# Regimes that contribute to modelo 349 (intracomunitario declarations)
_INTRA_REGIMES = {REGIME_EU_REVERSE_CHARGE, REGIME_INTRACOMUNITARIO}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_setting_float(db: AsyncSession, field: str, default: float) -> float:
    r = await db.execute(select(FinancialSettings))
    settings = r.scalars().first()
    if settings is None:
        return default
    return getattr(settings, field, default)


def _quarter_months(quarter: int) -> tuple[int, int]:
    start = (quarter - 1) * 3 + 1
    return start, start + 2


def _D(val) -> Decimal:
    """Safely convert to Decimal."""
    return Decimal(str(val or 0))


def _round2(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Modelo 303 — IVA Trimestral
# ---------------------------------------------------------------------------

async def _income_vat_for_quarter(db: AsyncSession, year: int, quarter: int) -> dict:
    """VAT on income for the quarter, broken down by regime."""
    m_start, m_end = _quarter_months(quarter)
    r = await db.execute(
        select(Income).where(
            extract("year", Income.date) == year,
            extract("month", Income.date) >= m_start,
            extract("month", Income.date) <= m_end,
        )
    )
    rows = r.scalars().all()

    vat_repercutido = Decimal("0")  # IVA we charge (standard operations)
    base_standard = Decimal("0")
    base_intra = Decimal("0")  # modelo 349
    base_export = Decimal("0")  # exempt

    for row in rows:
        regime = getattr(row, "tax_regime", REGIME_STANDARD) or REGIME_STANDARD
        amount = _D(row.amount)

        if regime == REGIME_STANDARD:
            base_standard += amount
            if row.vat_amount is not None:
                vat_repercutido += _D(row.vat_amount)
            else:
                vat_repercutido += amount * _D(row.vat_rate) / Decimal("100")

        elif regime in _INTRA_REGIMES:
            # Intracomunitario: no IVA charged, but declared in 349
            base_intra += amount

        elif regime == REGIME_EXPORT:
            base_export += amount

    return {
        "vat_repercutido": _round2(vat_repercutido),
        "base_standard": _round2(base_standard),
        "base_intra": _round2(base_intra),
        "base_export": _round2(base_export),
        "base_total": _round2(base_standard + base_intra + base_export),
    }


async def _expense_vat_for_quarter(db: AsyncSession, year: int, quarter: int) -> dict:
    """Deductible VAT on expenses for the quarter, broken down by regime."""
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

    vat_soportado = Decimal("0")  # IVA we can deduct (standard purchases)
    vat_reverse_charge = Decimal("0")  # IVA auto-repercutido (EU services received)
    base_standard = Decimal("0")
    base_intra = Decimal("0")

    for row in rows:
        regime = getattr(row, "tax_regime", REGIME_STANDARD) or REGIME_STANDARD
        amount = _D(row.amount)

        if regime == REGIME_STANDARD:
            base_standard += amount
            if row.vat_amount is not None:
                vat_soportado += _D(row.vat_amount)
            else:
                vat_soportado += amount * _D(row.vat_rate) / Decimal("100")

        elif regime in _INTRA_REGIMES:
            # Reverse charge: we auto-charge AND auto-deduct IVA (net zero for 303,
            # but must appear in both boxes). Use standard VAT rate for calculation.
            base_intra += amount
            auto_vat = amount * Decimal("21") / Decimal("100")  # always 21% for reverse charge
            vat_reverse_charge += auto_vat

    return {
        "vat_soportado": _round2(vat_soportado),
        "vat_reverse_charge": _round2(vat_reverse_charge),
        "base_standard": _round2(base_standard),
        "base_intra": _round2(base_intra),
        "base_total": _round2(base_standard + base_intra),
    }


async def calculate_iva_quarterly(db: AsyncSession, year: int, quarter: int) -> dict:
    """Modelo 303: IVA trimestral con soporte para reverse charge."""
    income_data = await _income_vat_for_quarter(db, year, quarter)
    expense_data = await _expense_vat_for_quarter(db, year, quarter)
    vat_rate = await _get_setting_float(db, "default_vat_rate", 21.0)

    # Casilla 01-09: IVA repercutido (standard operations)
    repercutido = Decimal(str(income_data["vat_repercutido"]))

    # Casilla 10-11: IVA reverse charge on intra-EU purchases
    # This is both added to repercutido AND soportado (net zero)
    reverse_charge = Decimal(str(expense_data["vat_reverse_charge"]))
    repercutido_total = repercutido + reverse_charge

    # Casilla 28-39: IVA soportado deducible
    soportado = Decimal(str(expense_data["vat_soportado"]))
    soportado_total = soportado + reverse_charge  # reverse charge is also deductible

    cuota = repercutido_total - soportado_total  # Net: reverse charge cancels out

    return {
        "name": f"IVA Trimestral Q{quarter}",
        "model": "303",
        "period": f"Q{quarter}",
        "year": year,
        "base_amount": income_data["base_standard"],
        "tax_rate": vat_rate,
        "tax_amount": _round2(cuota),
        # Extra detail for the tax advisor view
        "detail": {
            "vat_repercutido": income_data["vat_repercutido"],
            "vat_reverse_charge": expense_data["vat_reverse_charge"],
            "vat_repercutido_total": _round2(repercutido_total),
            "vat_soportado": expense_data["vat_soportado"],
            "vat_soportado_total": _round2(soportado_total),
            "income_base_standard": income_data["base_standard"],
            "income_base_intra": income_data["base_intra"],
            "income_base_export": income_data["base_export"],
            "expense_base_intra": expense_data["base_intra"],
        },
    }


# ---------------------------------------------------------------------------
# Modelo 349 — Declaración de operaciones intracomunitarias
# ---------------------------------------------------------------------------

async def calculate_modelo_349(db: AsyncSession, year: int, quarter: int) -> dict:
    """Modelo 349: intra-EU operations declaration."""
    m_start, m_end = _quarter_months(quarter)

    # Income: services/goods sold to EU (no IVA charged)
    r = await db.execute(
        select(Income).where(
            extract("year", Income.date) == year,
            extract("month", Income.date) >= m_start,
            extract("month", Income.date) <= m_end,
        )
    )
    income_rows = r.scalars().all()
    income_intra = Decimal("0")
    for row in income_rows:
        regime = getattr(row, "tax_regime", REGIME_STANDARD) or REGIME_STANDARD
        if regime in _INTRA_REGIMES:
            income_intra += _D(row.amount)

    # Expenses: services/goods purchased from EU (reverse charge)
    r = await db.execute(
        select(Expense).where(
            extract("year", Expense.date) == year,
            extract("month", Expense.date) >= m_start,
            extract("month", Expense.date) <= m_end,
        )
    )
    expense_rows = r.scalars().all()
    expense_intra = Decimal("0")
    for row in expense_rows:
        regime = getattr(row, "tax_regime", REGIME_STANDARD) or REGIME_STANDARD
        if regime in _INTRA_REGIMES:
            expense_intra += _D(row.amount)

    total_base = income_intra + expense_intra

    return {
        "name": f"Operaciones Intracomunitarias Q{quarter}",
        "model": "349",
        "period": f"Q{quarter}",
        "year": year,
        "base_amount": _round2(total_base),
        "tax_rate": 0.0,
        "tax_amount": 0.0,  # Informational, no tax to pay
        "detail": {
            "income_intra_eu": _round2(income_intra),
            "expense_intra_eu": _round2(expense_intra),
        },
    }


# ---------------------------------------------------------------------------
# Modelo 200 — Impuesto de Sociedades
# ---------------------------------------------------------------------------

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
        "base_amount": _round2(profit),
        "tax_rate": float(rate),
        "tax_amount": _round2(tax),
    }


# ---------------------------------------------------------------------------
# Modelo 111 — Retenciones IRPF
# ---------------------------------------------------------------------------

async def calculate_irpf_quarterly(db: AsyncSession, year: int, quarter: int) -> dict:
    """Modelo 111: IRPF withholdings on expenses.

    Uses actual irpf_withholding_amount from each expense if available,
    otherwise falls back to category-based estimation for backward compat.
    """
    m_start, m_end = _quarter_months(quarter)

    # Try real withholding data first (new fields)
    r = await db.execute(
        select(Expense).where(
            extract("year", Expense.date) == year,
            extract("month", Expense.date) >= m_start,
            extract("month", Expense.date) <= m_end,
        )
    )
    rows = r.scalars().all()

    base_with_irpf = Decimal("0")
    irpf_total = Decimal("0")
    has_real_data = False

    for row in rows:
        withholding = _D(getattr(row, "irpf_withholding_amount", 0))
        if withholding > 0:
            has_real_data = True
            irpf_total += withholding
            base_with_irpf += _D(row.amount)

    # Fallback: category-based estimation (backward compatibility)
    if not has_real_data:
        r = await db.execute(
            select(ExpenseCategory).where(ExpenseCategory.name == "Servicios profesionales")
        )
        cat = r.scalars().first()
        if cat:
            r = await db.execute(
                select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    extract("year", Expense.date) == year,
                    extract("month", Expense.date) >= m_start,
                    extract("month", Expense.date) <= m_end,
                    Expense.category_id == cat.id,
                )
            )
            base_with_irpf = Decimal(str(r.scalar()))
        rate = Decimal(str(await _get_setting_float(db, "irpf_retention_rate", 15.0)))
        irpf_total = base_with_irpf * rate / Decimal("100")

    # Also include IRPF withheld on income (retenciones que nos aplican a nosotros)
    r = await db.execute(
        select(Income).where(
            extract("year", Income.date) == year,
            extract("month", Income.date) >= m_start,
            extract("month", Income.date) <= m_end,
        )
    )
    income_rows = r.scalars().all()
    income_irpf = Decimal("0")
    for row in income_rows:
        income_irpf += _D(getattr(row, "irpf_withholding_amount", 0))

    rate = await _get_setting_float(db, "irpf_retention_rate", 15.0)

    return {
        "name": f"Retenciones IRPF Q{quarter}",
        "model": "111",
        "period": f"Q{quarter}",
        "year": year,
        "base_amount": _round2(base_with_irpf),
        "tax_rate": rate,
        "tax_amount": _round2(irpf_total),
        "detail": {
            "irpf_on_expenses": _round2(irpf_total),
            "irpf_on_income": _round2(income_irpf),
            "uses_real_data": has_real_data,
        },
    }


# ---------------------------------------------------------------------------
# Calendar / deadlines
# ---------------------------------------------------------------------------

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
        {"model": "349", "period": "Q1", "due_date": f"{year}-04-20", "description": "Op. Intracomunitarias 1T"},
        {"model": "349", "period": "Q2", "due_date": f"{year}-07-20", "description": "Op. Intracomunitarias 2T"},
        {"model": "349", "period": "Q3", "due_date": f"{year}-10-20", "description": "Op. Intracomunitarias 3T"},
        {"model": "349", "period": "Q4", "due_date": f"{year + 1}-01-20", "description": "Op. Intracomunitarias 4T"},
        {"model": "200", "period": "anual", "due_date": f"{year + 1}-07-25", "description": "Impuesto Sociedades"},
    ]


def _due_date_for(model: str, period: str, year: int) -> Optional[date]:
    for d in get_fiscal_deadlines(year):
        if d["model"] == model and d["period"] == period:
            return date.fromisoformat(d["due_date"])
    return None


# ---------------------------------------------------------------------------
# Upsert & calculate all
# ---------------------------------------------------------------------------

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

        # Only create 349 if there are intra-EU operations
        m349 = await calculate_modelo_349(db, year, q)
        if m349["base_amount"] > 0:
            results.append(await _upsert_tax(db, m349))

    corp = await calculate_corporate_tax(db, year)
    results.append(await _upsert_tax(db, corp))

    await db.commit()
    for r_item in results:
        await db.refresh(r_item)
    return results
