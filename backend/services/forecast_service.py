from __future__ import annotations

import asyncio
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from sqlalchemy import select, extract, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Forecast, Income, Expense, Tax, BalanceSnapshot, FinancialSettings


async def calculate_historical_averages(db: AsyncSession, lookback: int = 6) -> dict:
    today = date.today()
    start = today - timedelta(days=lookback * 31)
    r = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.date >= start)
    )
    income_total = float(r.scalar())
    r = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.date >= start)
    )
    expense_total = float(r.scalar())
    months = max(lookback, 1)
    return {
        "avg_income": round(income_total / months, 2),
        "avg_expenses": round(expense_total / months, 2),
    }


async def get_recurring_baseline(db: AsyncSession) -> dict:
    # Recurring income
    r = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.type == "recurrente")
    )
    recurring_income = float(r.scalar())

    # Count distinct months with recurring income (PostgreSQL compatible)
    r = await db.execute(
        select(func.count(func.distinct(
            func.concat(extract("year", Income.date), "-", extract("month", Income.date))
        )))
        .where(Income.type == "recurrente")
    )
    income_months = r.scalar() or 1

    # Recurring expenses
    r = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.is_recurring.is_(True))
    )
    recurring_expenses = float(r.scalar())

    r = await db.execute(
        select(func.count(func.distinct(
            func.concat(extract("year", Expense.date), "-", extract("month", Expense.date))
        )))
        .where(Expense.is_recurring.is_(True))
    )
    expense_months = r.scalar() or 1

    return {
        "recurring_income": round(recurring_income / income_months, 2),
        "recurring_expenses": round(recurring_expenses / expense_months, 2),
    }


async def generate_forecasts(db: AsyncSession, months_ahead: int = 6) -> list[Forecast]:
    averages = await calculate_historical_averages(db)
    recurring = await get_recurring_baseline(db)

    proj_income = max(averages["avg_income"], recurring["recurring_income"])
    proj_expenses = max(averages["avg_expenses"], recurring["recurring_expenses"])

    # Load tax rates from financial settings (fallback to sensible defaults)
    fs_result = await db.execute(select(FinancialSettings).limit(1))
    fs = fs_result.scalars().first()
    vat_rate = float(fs.default_vat_rate) if fs and fs.default_vat_rate else 21.0
    corp_tax_rate = float(fs.corporate_tax_rate) if fs and fs.corporate_tax_rate else 25.0

    # Calculate average actual VAT differential from recent income/expenses
    today = date.today()
    lookback_months = 6
    recent_cutoff = today - timedelta(days=lookback_months * 31)
    r_inc_vat = await db.execute(
        select(func.coalesce(func.sum(Income.vat_amount), 0))
        .where(Income.date >= recent_cutoff)
    )
    avg_income_vat = float(r_inc_vat.scalar()) / lookback_months
    r_exp_vat = await db.execute(
        select(func.coalesce(func.sum(Expense.vat_amount), 0))
        .where(Expense.date >= recent_cutoff, Expense.is_deductible.is_(True))
    )
    avg_expense_vat = float(r_exp_vat.scalar()) / lookback_months
    results = []
    for i in range(1, months_ahead + 1):
        month_date = (today + relativedelta(months=i)).replace(day=1)
        confidence = round(max(0.3, 0.85 - (i - 1) * 0.1), 2)
        # VAT reserve: use actual average VAT repercutido - soportado
        proj_vat_reserve = round(avg_income_vat - avg_expense_vat, 2)
        # Corporate tax on projected profit (only if positive)
        proj_corporate_tax = round(max(proj_income - proj_expenses, 0) * (corp_tax_rate / 100), 2)
        proj_taxes = round(max(proj_vat_reserve, 0) + proj_corporate_tax, 2)
        proj_profit = round(proj_income - proj_expenses - proj_taxes, 2)

        r = await db.execute(select(Forecast).where(Forecast.month == month_date))
        existing = r.scalars().first()
        if existing:
            existing.projected_income = round(proj_income, 2)
            existing.projected_expenses = round(proj_expenses, 2)
            existing.projected_taxes = proj_taxes
            existing.projected_profit = proj_profit
            existing.confidence = confidence
            results.append(existing)
        else:
            f = Forecast(
                month=month_date,
                projected_income=round(proj_income, 2),
                projected_expenses=round(proj_expenses, 2),
                projected_taxes=proj_taxes,
                projected_profit=proj_profit,
                confidence=confidence,
            )
            db.add(f)
            results.append(f)

    await db.commit()
    for r_item in results:
        await db.refresh(r_item)
    return results


async def calculate_runway(db: AsyncSession) -> dict:
    today = date.today()
    year = today.year

    # Check for a recent manual balance snapshot (within 45 days)
    cutoff = today - timedelta(days=45)
    r = await db.execute(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.date >= cutoff)
        .order_by(BalanceSnapshot.date.desc())
        .limit(1)
    )
    latest_snapshot = r.scalars().first()

    if latest_snapshot:
        cash = latest_snapshot.amount
        balance_source = "manual"
        balance_date = latest_snapshot.date.isoformat()
    else:
        ri, re, rt = await asyncio.gather(
            db.execute(
                select(func.coalesce(func.sum(Income.amount), 0))
                .where(extract("year", Income.date) == year)
            ),
            db.execute(
                select(func.coalesce(func.sum(Expense.amount), 0))
                .where(extract("year", Expense.date) == year)
            ),
            db.execute(
                select(func.coalesce(func.sum(Tax.tax_amount), 0))
                .where(Tax.year == year, Tax.status == "pagado")
            ),
        )
        ytd_income = float(ri.scalar())
        ytd_expenses = float(re.scalar())
        ytd_taxes_paid = float(rt.scalar())

        # Fallback: approximate cash from YTD data (not real bank balance)
        cash = ytd_income - ytd_expenses - ytd_taxes_paid
        balance_source = "calculated"
        balance_date = None

    averages = await calculate_historical_averages(db)
    monthly_burn = averages["avg_expenses"]
    runway_months = round(cash / monthly_burn, 1) if monthly_burn > 0 else None

    runway_date = None
    if runway_months is not None:
        runway_date = (today + timedelta(days=int(runway_months * 30))).isoformat()

    return {
        "current_cash": round(cash, 2),
        "avg_monthly_burn": monthly_burn,
        "runway_months": runway_months,
        "runway_date": runway_date,
        "source": balance_source,
        "balance_date": balance_date,
    }


async def get_vs_actual(db: AsyncSession, year: int) -> list[dict]:
    today = date.today()
    if year < today.year:
        max_month = 12
    elif year == today.year:
        max_month = today.month
    else:
        return []

    # Batch query: actual income grouped by month
    r_inc = await db.execute(
        select(
            extract("month", Income.date).label("month"),
            func.coalesce(func.sum(Income.amount), 0).label("total"),
        )
        .where(extract("year", Income.date) == year)
        .group_by(extract("month", Income.date))
    )
    income_by_month = {int(row.month): float(row.total) for row in r_inc.all()}

    # Batch query: actual expenses grouped by month
    r_exp = await db.execute(
        select(
            extract("month", Expense.date).label("month"),
            func.coalesce(func.sum(Expense.amount), 0).label("total"),
        )
        .where(extract("year", Expense.date) == year)
        .group_by(extract("month", Expense.date))
    )
    expenses_by_month = {int(row.month): float(row.total) for row in r_exp.all()}

    # Prefetch all forecasts for this year
    r_fc = await db.execute(
        select(Forecast).where(extract("year", Forecast.month) == year)
    )
    forecast_map = {f.month.month: f for f in r_fc.scalars().all()}

    result = []
    for m in range(1, max_month + 1):
        actual_income = income_by_month.get(m, 0.0)
        actual_expenses = expenses_by_month.get(m, 0.0)
        f = forecast_map.get(m)
        result.append({
            "month": date(year, m, 1).isoformat(),
            "projected_income": f.projected_income if f else 0,
            "projected_expenses": f.projected_expenses if f else 0,
            "projected_profit": f.projected_profit if f else 0,
            "actual_income": round(actual_income, 2),
            "actual_expenses": round(actual_expenses, 2),
            "actual_profit": round(actual_income - actual_expenses, 2),
        })
    return result
