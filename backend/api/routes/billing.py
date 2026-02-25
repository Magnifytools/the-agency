from __future__ import annotations
from typing import Optional

import csv
import io
from datetime import datetime, timezone
from calendar import monthrange

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Client, Task, TimeEntry, User
from backend.api.deps import get_current_user, require_module

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _month_range(year: int, month: int):
    """Return naive datetimes (no tz) to match TIMESTAMP WITHOUT TIME ZONE columns."""
    _, last_day = monthrange(year, month)
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


@router.get("/export")
async def export_billing(
    format: str = Query("csv", pattern="^(csv|json)$"),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("billing")),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start, end = _month_range(y, m)

    # Aggregate time + cost per client for the month
    result = await db.execute(
        select(
            Client.id,
            Client.name,
            Client.monthly_budget,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("total_minutes"),
            func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0).label("total_cost"),
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
        rows.append({
            "client_id": row.id,
            "client_name": row.name,
            "period": f"{y}-{m:02d}",
            "hours": hours,
            "cost": cost,
            "budget": budget,
            "margin": round(budget - cost, 2),
        })

    if format == "json":
        return rows

    # CSV export
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["client_id", "client_name", "period", "hours", "cost", "budget", "margin"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    content = output.getvalue()
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=billing_{y}_{m:02d}.csv"},
    )
