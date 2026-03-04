from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Client, Task, TimeEntry, User, Income
from backend.api.deps import require_module
from backend.services.csv_utils import build_csv_response
from backend.services.report_period import (
    MAX_REPORT_YEAR,
    MIN_REPORT_YEAR,
    month_range_naive,
    resolve_default_period,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/export")
async def export_billing(
    format: str = Query("csv", pattern="^(csv|json)$"),
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("billing")),
):
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Subquery: real invoiced income per client for the period (cobrado + pendiente)
    invoiced_subq = (
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(
            Income.client_id == Client.id,
            Income.date >= start,
            Income.date <= end,
        )
        .scalar_subquery()
    )

    # Aggregate time + cost per client for the month
    result = await db.execute(
        select(
            Client.id,
            Client.name,
            Client.monthly_budget,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("total_minutes"),
            func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0).label("total_cost"),
            invoiced_subq.label("invoiced"),
        )
        .select_from(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(Client, Task.client_id == Client.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            and_(
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= start,
                TimeEntry.date <= end,
            )
        )
        .group_by(Client.id)
        .order_by(Client.name)
    )

    rows = []
    for row in result.all():
        hours = round((row.total_minutes or 0) / 60, 2)
        cost = round(row.total_cost or 0, 2)
        budget = float(row.monthly_budget or 0)
        invoiced = round(float(row.invoiced or 0), 2)
        margin = round(invoiced - cost, 2) if invoiced > 0 else round(budget - cost, 2)
        rows.append({
            "client_id": row.id,
            "client_name": row.name,
            "period": f"{y}-{m:02d}",
            "hours": hours,
            "cost": cost,
            "budget": budget,
            "invoiced": invoiced,
            "margin": margin,
        })

    if format == "json":
        return rows

    # CSV export
    header = ["client_id", "client_name", "period", "hours", "cost", "budget", "invoiced", "margin"]
    csv_rows = (
        [r["client_id"], r["client_name"], r["period"], r["hours"], r["cost"], r["budget"], r["invoiced"], r["margin"]]
        for r in rows
    )
    return build_csv_response(f"billing_{y}_{m:02d}.csv", header, csv_rows)
