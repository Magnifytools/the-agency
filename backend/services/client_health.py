"""Client Health Score — computed in real-time from existing data.

Score 0-100 based on 5 weighted factors:
  - Communication frequency  (25 pts)
  - Task completion rate      (25 pts)
  - Digest coverage           (15 pts)
  - Profitability              (20 pts)
  - Follow-up compliance       (15 pts)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client, ClientStatus, CommunicationLog, Task, TaskStatus,
    WeeklyDigest, TimeEntry,
)


async def compute_health(client: Client, db: AsyncSession) -> dict:
    """Return health score dict for a single client."""
    now = datetime.now(timezone.utc)

    # --- 1. Communication frequency (25 pts) ---
    # Score based on days since last communication
    last_comm = await db.execute(
        select(func.max(CommunicationLog.occurred_at))
        .where(CommunicationLog.client_id == client.id)
    )
    last_comm_date = last_comm.scalar()
    if last_comm_date:
        if last_comm_date.tzinfo is None:
            from datetime import timezone as tz
            last_comm_date = last_comm_date.replace(tzinfo=tz.utc)
        days_since = (now - last_comm_date).days
        if days_since <= 3:
            comm_score = 25
        elif days_since <= 7:
            comm_score = 20
        elif days_since <= 14:
            comm_score = 15
        elif days_since <= 30:
            comm_score = 8
        else:
            comm_score = 0
    else:
        comm_score = 0

    # --- 2. Task completion (25 pts) ---
    task_counts = await db.execute(
        select(Task.status, func.count())
        .where(Task.client_id == client.id)
        .group_by(Task.status)
    )
    task_map = dict(task_counts.all())
    total_tasks = sum(task_map.values())
    completed = task_map.get(TaskStatus.completed, 0)
    pending = task_map.get(TaskStatus.pending, 0)
    in_progress = task_map.get(TaskStatus.in_progress, 0)

    if total_tasks == 0:
        task_score = 15  # neutral — no tasks yet
    else:
        completion_rate = completed / total_tasks
        # Check overdue
        overdue_count_result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.client_id == client.id,
                Task.status != TaskStatus.completed,
                Task.due_date < now,
            )
        )
        overdue = overdue_count_result.scalar() or 0
        task_score = int(completion_rate * 20)
        # Bonus for no overdue, penalty for overdue
        if overdue == 0:
            task_score += 5
        else:
            task_score = max(0, task_score - min(overdue * 3, 10))

    # --- 3. Digest coverage (15 pts) ---
    # How many of the last 4 weeks had digests?
    four_weeks_ago = (now - timedelta(weeks=4)).date()
    digest_count_result = await db.execute(
        select(func.count()).select_from(WeeklyDigest).where(
            WeeklyDigest.client_id == client.id,
            WeeklyDigest.period_start >= four_weeks_ago,
        )
    )
    digest_count = digest_count_result.scalar() or 0
    digest_score = min(digest_count, 4) * 4  # max 16, capped at 15
    digest_score = min(digest_score, 15)

    # --- 4. Profitability (20 pts) ---
    # Compare budget vs actual hours cost
    if client.monthly_budget and client.monthly_budget > 0:
        # Get total tracked minutes this month
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tracked_result = await db.execute(
            select(func.coalesce(func.sum(TimeEntry.minutes), 0))
            .join(Task, TimeEntry.task_id == Task.id)
            .where(Task.client_id == client.id, TimeEntry.date >= month_start)
        )
        tracked_minutes = tracked_result.scalar() or 0
        # Rough cost estimate: assume avg 40 EUR/h
        estimated_cost = (tracked_minutes / 60) * 40
        ratio = estimated_cost / client.monthly_budget
        if ratio <= 0.7:
            profit_score = 20
        elif ratio <= 0.9:
            profit_score = 15
        elif ratio <= 1.0:
            profit_score = 10
        elif ratio <= 1.2:
            profit_score = 5
        else:
            profit_score = 0
    else:
        profit_score = 10  # neutral — no budget set

    # --- 5. Follow-up compliance (15 pts) ---
    pending_followups_result = await db.execute(
        select(func.count()).select_from(CommunicationLog).where(
            CommunicationLog.client_id == client.id,
            CommunicationLog.requires_followup == True,
            CommunicationLog.followup_date < now,
        )
    )
    overdue_followups = pending_followups_result.scalar() or 0
    if overdue_followups == 0:
        followup_score = 15
    elif overdue_followups <= 2:
        followup_score = 8
    else:
        followup_score = 0

    total = comm_score + task_score + digest_score + profit_score + followup_score
    total = max(0, min(100, total))

    if total >= 70:
        risk_level = "healthy"
    elif total >= 40:
        risk_level = "warning"
    else:
        risk_level = "at_risk"

    return {
        "client_id": client.id,
        "client_name": client.name,
        "score": total,
        "factors": {
            "communication": comm_score,
            "tasks": task_score,
            "digests": digest_score,
            "profitability": profit_score,
            "followups": followup_score,
        },
        "risk_level": risk_level,
    }
