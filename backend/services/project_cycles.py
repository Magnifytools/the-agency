"""Monthly operational cycle for recurring projects."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select

from backend.db.models import Project, Task, TimeEntry
from backend.services.hours_carryover import month_budget, project_month_budget
from backend.services.temporal import business_today, civil_day_utc_bounds
from backend.services.time_budget import effective_budgets, is_recurring_project
from backend.services.time_entry_dates import time_entry_civil_period


def month_bounds(month: str | None) -> tuple[date, date, str]:
    if month is None:
        start = business_today().replace(day=1)
    else:
        if len(month) != 7 or month[4] != "-":
            raise ValueError("month must use YYYY-MM")
        try:
            start = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError("month must use YYYY-MM") from exc
    if start.year == 9999 and start.month == 12:
        raise ValueError("month is outside the supported range")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end, start.strftime("%Y-%m")


async def collect_project_monthly_cycle(
    db, project_id: int, month: str | None, *, include_hours: bool = True,
):
    project = (
        await db.execute(
            select(
                Project.id,
                Project.is_recurring,
                Project.pricing_model,
                Project.budget_hours,
                Project.weekly_hours_budget,
                Project.monthly_hours_budget,
                Project.hours_carryover,
                Project.start_date,
                Project.created_at,
            ).where(Project.id == project_id)
        )
    ).one_or_none()
    if project is None:
        return None
    if not is_recurring_project(project):
        raise TypeError("monthly cycle only applies to recurring projects")

    start, end, month_key = month_bounds(month)
    completed_start, _ = civil_day_utc_bounds(start)
    completed_end, _ = civil_day_utc_bounds(end)
    rows = (
        await db.execute(
            select(
                Task.id,
                Task.title,
                Task.status,
                Task.scheduled_date,
                Task.completed_at,
            )
            .where(
                Task.project_id == project_id,
                Task.is_recurring.is_(False),
                or_(
                    and_(Task.scheduled_date >= start, Task.scheduled_date < end),
                    and_(
                        Task.completed_at >= completed_start,
                        Task.completed_at < completed_end,
                    ),
                ),
            )
            .order_by(Task.scheduled_date.asc().nullslast(), Task.completed_at, Task.id)
        )
    ).all()
    total_minutes = None
    if include_hours:
        total_minutes = float(
            (
                await db.scalar(
                    select(func.coalesce(func.sum(TimeEntry.minutes), 0))
                    .join(Task, Task.id == TimeEntry.task_id)
                    .where(
                        Task.project_id == project_id,
                        TimeEntry.minutes.is_not(None),
                        time_entry_civil_period(start, end),
                    )
                )
            )
            or 0
        )
    _, monthly_budget = effective_budgets(project)
    used_hours = round(total_minutes / 60, 2) if total_minutes is not None else None
    # El arrastre sale de las horas del mes anterior: sólo con lectura de horas.
    month = (
        await project_month_budget(db, project, monthly_budget, start) if include_hours
        else month_budget(monthly_budget, carryover=False, previous_minutes=None, eligible=False)
    )
    budget = round(month.budget, 2) if month.budget is not None else None
    return {
        "project_id": project_id,
        "month": month_key,
        "period_start": start,
        "period_end": end,
        "planned_count": sum(row.scheduled_date is not None and start <= row.scheduled_date < end for row in rows),
        "completed_in_month_count": sum(
            row.completed_at is not None
            and completed_start <= row.completed_at < completed_end
            for row in rows
        ),
        "total_minutes": int(total_minutes) if total_minutes is not None else None,
        "used_hours": used_hours,
        "budget_hours": budget,
        "base_budget_hours": round(month.base, 2) if month.base is not None else None,
        "carried_hours": round(month.carried, 2) if month.carried is not None else None,
        "remaining_hours": round(budget - used_hours, 2) if budget is not None and used_hours is not None else None,
        "tasks": [
            {
                "id": row.id,
                "title": row.title,
                "status": row.status.value,
                "scheduled_date": row.scheduled_date,
                "completed_at": row.completed_at,
            }
            for row in rows
        ],
    }
