"""Client dashboard API — aggregated KPIs per client."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, extract, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    User, Client, Task, TaskStatus, TimeEntry, TaskCategory,
)
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/clients/{client_id}/dashboard", tags=["client-dashboard"])


@router.get("")
async def client_dashboard(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    first_of_month = today.replace(day=1)
    if today.month == 1:
        first_of_last_month = today.replace(year=today.year - 1, month=12, day=1)
    else:
        first_of_last_month = today.replace(month=today.month - 1, day=1)

    # --- Tasks by status ---
    task_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.client_id == client_id)
        .group_by(Task.status)
    )
    tasks_by_status = {row[0].value: row[1] for row in task_result.all()}

    # Overdue tasks
    now = datetime.utcnow()
    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.due_date < now,
            Task.status != TaskStatus.completed,
        )
    )
    tasks_overdue = overdue_result.scalar() or 0

    # Tasks due this week
    week_end = today + timedelta(days=(6 - today.weekday()))
    due_week_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.due_date <= datetime.combine(week_end, datetime.max.time()),
            Task.due_date >= datetime.combine(today, datetime.min.time()),
            Task.status != TaskStatus.completed,
        )
    )
    tasks_due_this_week = due_week_result.scalar() or 0

    # --- Hours this month ---
    # Get all task IDs for this client
    task_ids_result = await db.execute(
        select(Task.id).where(Task.client_id == client_id)
    )
    task_ids = [r[0] for r in task_ids_result.all()]

    hours_this_month = 0.0
    hours_last_month = 0.0
    total_cost_this_month = 0.0
    team_breakdown: dict[int, dict] = {}
    monthly_hours: dict[str, float] = {}

    if task_ids:
        # Hours this month with user info
        entries_this_month = await db.execute(
            select(TimeEntry.minutes, TimeEntry.user_id, User.full_name, User.hourly_rate)
            .join(User, TimeEntry.user_id == User.id)
            .where(
                TimeEntry.task_id.in_(task_ids),
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= datetime.combine(first_of_month, datetime.min.time()),
            )
        )
        for minutes, user_id, full_name, hourly_rate in entries_this_month.all():
            hrs = (minutes or 0) / 60
            hours_this_month += hrs
            rate = hourly_rate or 0
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
                TimeEntry.task_id.in_(task_ids),
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= datetime.combine(first_of_last_month, datetime.min.time()),
                TimeEntry.date < datetime.combine(first_of_month, datetime.min.time()),
            )
        )
        last_month_mins = last_month_result.scalar() or 0
        hours_last_month = last_month_mins / 60

        # Monthly breakdown (last 6 months)
        six_months_ago = today.replace(day=1)
        for _ in range(6):
            if six_months_ago.month == 1:
                six_months_ago = six_months_ago.replace(year=six_months_ago.year - 1, month=12)
            else:
                six_months_ago = six_months_ago.replace(month=six_months_ago.month - 1)

        monthly_result = await db.execute(
            select(
                extract("year", TimeEntry.date).label("yr"),
                extract("month", TimeEntry.date).label("mo"),
                func.sum(TimeEntry.minutes),
            )
            .where(
                TimeEntry.task_id.in_(task_ids),
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= datetime.combine(six_months_ago, datetime.min.time()),
            )
            .group_by("yr", "mo")
            .order_by("yr", "mo")
        )
        for yr, mo, total_mins in monthly_result.all():
            key = f"{int(yr)}-{int(mo):02d}"
            monthly_hours[key] = round((total_mins or 0) / 60, 1)

    # --- Client financial data ---
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    monthly_fee = client.monthly_fee or 0 if client else 0
    monthly_budget = client.monthly_budget or 0 if client else 0

    margin = monthly_fee - total_cost_this_month
    margin_pct = round((margin / monthly_fee) * 100, 1) if monthly_fee > 0 else 0
    hours_trend_pct = 0.0
    if hours_last_month > 0:
        hours_trend_pct = round(((hours_this_month - hours_last_month) / hours_last_month) * 100, 1)

    profitability_status = "profitable"
    if margin_pct < 10:
        profitability_status = "unprofitable"
    elif margin_pct < 30:
        profitability_status = "at_risk"

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
    }
