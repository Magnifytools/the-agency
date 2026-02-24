from __future__ import annotations

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from sqlalchemy import select, extract, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Forecast, Income, Expense, Tax


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

    today = date.today()
    results = []
    for i in range(1, months_ahead + 1):
        month_date = (today + relativedelta(months=i)).replace(day=1)
        confidence = round(max(0.3, 0.85 - (i - 1) * 0.1), 2)
        proj_taxes = round(proj_income * 0.21 * 0.25, 2)
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

    r = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(extract("year", Income.date) == year)
    )
    ytd_income = float(r.scalar())

    r = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(extract("year", Expense.date) == year)
    )
    ytd_expenses = float(r.scalar())

    r = await db.execute(
        select(func.coalesce(func.sum(Tax.tax_amount), 0))
        .where(Tax.year == year, Tax.status == "pagado")
    )
    ytd_taxes_paid = float(r.scalar())

    cash = ytd_income - ytd_expenses - ytd_taxes_paid
    averages = await calculate_historical_averages(db)
    monthly_burn = averages["avg_expenses"]
    runway_months = round(cash / monthly_burn, 1) if monthly_burn > 0 else 99

    runway_date = None
    if monthly_burn > 0 and runway_months < 99:
        runway_date = (today + timedelta(days=int(runway_months * 30))).isoformat()

    return {
        "current_cash": round(cash, 2),
        "avg_monthly_burn": monthly_burn,
        "runway_months": runway_months,
        "runway_date": runway_date,
    }


async def get_vs_actual(db: AsyncSession, year: int) -> list[dict]:
    r = await db.execute(
        select(Forecast)
        .where(extract("year", Forecast.month) == year)
        .order_by(Forecast.month)
    )
    forecasts = r.scalars().all()
    result = []
    for f in forecasts:
        m = f.month.month
        r = await db.execute(
            select(func.coalesce(func.sum(Income.amount), 0))
            .where(extract("year", Income.date) == year, extract("month", Income.date) == m)
        )
        actual_income = float(r.scalar())
        r = await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0))
            .where(extract("year", Expense.date) == year, extract("month", Expense.date) == m)
        )
        actual_expenses = float(r.scalar())
        result.append({
            "month": f.month.isoformat(),
            "projected_income": f.projected_income,
            "projected_expenses": f.projected_expenses,
            "projected_profit": f.projected_profit,
            "actual_income": round(actual_income, 2),
            "actual_expenses": round(actual_expenses, 2),
            "actual_profit": round(actual_income - actual_expenses, 2),
        })
    return result
