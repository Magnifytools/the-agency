"""Client dashboard API — aggregated KPIs per client."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Date as SQLDate, cast, select, func, extract, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    User, Client, Project, ProjectStatus, Task, TaskStatus, TimeEntry, TaskCategory, Income,
)
from backend.schemas.dashboard import ClientDashboardResponse
from backend.services.profitability import classify_profitability
from backend.api.deps import get_current_user, require_module
from backend.services.temporal import business_today
from backend.services.time_entry_dates import time_entry_business_date, time_entry_civil_period

router = APIRouter(prefix="/api/clients/{client_id}/dashboard", tags=["client-dashboard"])


@router.get("", response_model=ClientDashboardResponse)
async def client_dashboard(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    today = business_today()
    first_of_month = today.replace(day=1)
    first_of_last_month = (first_of_month - timedelta(days=1)).replace(day=1)
    next_month = (first_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    # --- Tasks by status ---
    task_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.client_id == client_id, Task.retired_at.is_(None))
        .group_by(Task.status)
    )
    tasks_by_status = {row[0].value: row[1] for row in task_result.all()}

    # Overdue tasks
    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.retired_at.is_(None),
            cast(Task.due_date, SQLDate) < today,
            Task.status != TaskStatus.completed,
        )
    )
    tasks_overdue = overdue_result.scalar() or 0

    # Tasks due this week
    week_end = today + timedelta(days=(6 - today.weekday()))
    due_week_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.retired_at.is_(None),
            cast(Task.due_date, SQLDate) <= week_end,
            cast(Task.due_date, SQLDate) >= today,
            Task.status != TaskStatus.completed,
        )
    )
    tasks_due_this_week = due_week_result.scalar() or 0

    # --- Hours (using subquery to avoid N+1) ---
    task_subq = select(Task.id).where(Task.client_id == client_id).scalar_subquery()

    hours_this_month = 0.0
    hours_last_month = 0.0
    total_cost_this_month = 0.0
    team_breakdown: dict[int, dict] = {}
    monthly_hours: dict[str, float] = {}

    # Hours this month with user info
    entries_this_month = await db.execute(
        select(TimeEntry.minutes, TimeEntry.user_id, User.full_name, User.hourly_rate)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            TimeEntry.task_id.in_(task_subq),
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(first_of_month, next_month),
        )
    )
    for minutes, user_id, full_name, hourly_rate in entries_this_month.all():
        hrs = (minutes or 0) / 60
        hours_this_month += hrs
        rate = float(hourly_rate or 0)
        cost = hrs * rate
        total_cost_this_month += cost

        if user_id not in team_breakdown:
            team_breakdown[user_id] = {
                "user_id": user_id,
                "full_name": full_name,
                "hours": 0.0,
                "cost": 0.0,
            }
        team_breakdown[user_id]["hours"] += hrs
        team_breakdown[user_id]["cost"] += cost

    # Hours last month
    last_month_result = await db.execute(
        select(func.sum(TimeEntry.minutes)).where(
            TimeEntry.task_id.in_(task_subq),
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(first_of_last_month, first_of_month),
        )
    )
    last_month_mins = last_month_result.scalar() or 0
    hours_last_month = last_month_mins / 60

    # Monthly breakdown (last 6 months)
    six_months_ago = first_of_month
    for _ in range(6):
        six_months_ago = (six_months_ago - timedelta(days=1)).replace(day=1)

    monthly_result = await db.execute(
        select(
            TimeEntry.date,
            TimeEntry.started_at,
            TimeEntry.minutes,
            User.hourly_rate,
        )
        .join(User, TimeEntry.user_id == User.id)
        .where(
            TimeEntry.task_id.in_(task_subq),
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(six_months_ago, next_month),
        )
    )
    monthly_rows = monthly_result.all()
    monthly_minutes: dict[str, int] = {}
    monthly_costs: dict[str, float] = {}
    for entry_date, started_at, minutes, hourly_rate in monthly_rows:
        day = time_entry_business_date(entry_date, started_at)
        key = f"{day.year}-{day.month:02d}"
        monthly_minutes[key] = monthly_minutes.get(key, 0) + (minutes or 0)
        monthly_costs[key] = monthly_costs.get(key, 0) + (minutes or 0) * float(hourly_rate or 0) / 60
    monthly_hours = {key: round(minutes / 60, 1) for key, minutes in monthly_minutes.items()}

    # --- Monthly profitability breakdown (last 6 months): income vs cost ---
    monthly_profitability: dict[str, dict] = {}

    # Monthly income from Income table
    income_monthly = await db.execute(
        select(
            extract("year", Income.date).label("yr"),
            extract("month", Income.date).label("mo"),
            func.sum(Income.amount),
        )
        .where(
            Income.client_id == client_id,
            Income.date >= six_months_ago,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
    )
    for yr, mo, total_amount in income_monthly.all():
        key = f"{int(yr)}-{int(mo):02d}"
        monthly_profitability[key] = {"income": round(float(total_amount or 0), 2), "cost": 0.0}

    # Monthly cost uses the same resolved business month as the hours series.
    for key, total_cost_val in monthly_costs.items():
        if key not in monthly_profitability:
            monthly_profitability[key] = {"income": 0.0, "cost": 0.0}
        monthly_profitability[key]["cost"] = round(total_cost_val, 2)

    # --- Client financial data: derive from active projects, fallback to client fields ---
    project_fee_result = await db.execute(
        select(func.coalesce(func.sum(Project.monthly_fee), 0))
        .where(Project.client_id == client_id, Project.status == ProjectStatus.active)
    )
    project_fee_total = float(project_fee_result.scalar() or 0)

    client_result = await db.execute(
        select(Client.monthly_fee, Client.monthly_budget)
        .where(Client.id == client_id)
    )
    row = client_result.one_or_none()
    legacy_fee = float(row[0] or 0) if row else 0
    legacy_budget = float(row[1] or 0) if row else 0

    # Prefer project-derived fee; fall back to legacy client fields
    monthly_fee = project_fee_total or legacy_fee
    monthly_budget = project_fee_total or legacy_budget

    # --- Actual income from Income table this month ---
    income_result = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.client_id == client_id, Income.date >= first_of_month)
    )
    actual_income = float(income_result.scalar() or 0)

    margin = monthly_fee - total_cost_this_month
    margin_pct = round((margin / monthly_fee) * 100, 1) if monthly_fee > 0 else 0
    hours_trend_pct = 0.0
    if hours_last_month > 0:
        hours_trend_pct = round(((hours_this_month - hours_last_month) / hours_last_month) * 100, 1)

    profitability_status = classify_profitability(
        budget=monthly_fee,
        margin=margin,
        margin_pct=margin_pct,
        profitable_at_pct=30,
        unprofitable_below_pct=10,
    )

    return {
        "hours_this_month": round(hours_this_month, 1),
        "hours_last_month": round(hours_last_month, 1),
        "hours_trend_pct": hours_trend_pct,
        "total_cost_this_month": round(total_cost_this_month, 2),
        "monthly_fee": monthly_fee,
        "monthly_budget": monthly_budget,
        "margin": round(margin, 2),
        "margin_pct": margin_pct,
        "profitability_status": profitability_status,
        "tasks_by_status": tasks_by_status,
        "tasks_overdue": tasks_overdue,
        "tasks_due_this_week": tasks_due_this_week,
        "monthly_hours_breakdown": monthly_hours,
        "team_breakdown": list(team_breakdown.values()),
        "actual_income": round(actual_income, 2),
        "monthly_profitability": monthly_profitability,
    }
