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
from typing import List

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, CommunicationLog, Task, TaskStatus,
    WeeklyDigest, TimeEntry, User,
)


# ── Scoring helpers ──────────────────────────────────────────


def _comm_score_from_days(days_since: int | None) -> int:
    """Communication score (25 pts) based on days since last contact."""
    if days_since is None:
        return 0
    if days_since <= 3:
        return 25
    if days_since <= 7:
        return 20
    if days_since <= 14:
        return 15
    if days_since <= 30:
        return 8
    return 0


def _task_score_from_counts(total: int, completed: int, overdue: int) -> int:
    """Task completion score (25 pts)."""
    if total == 0:
        return 15  # neutral — no tasks yet
    completion_rate = completed / total
    score = int(completion_rate * 20)
    if overdue == 0:
        score += 5
    else:
        score = max(0, score - min(overdue * 3, 10))
    return score


def _digest_score_from_count(digest_count: int) -> int:
    """Digest coverage score (15 pts)."""
    return min(min(digest_count, 4) * 4, 15)


def _profit_score_from_cost(monthly_budget: float | None, estimated_cost: float) -> int:
    """Profitability score (20 pts)."""
    if not monthly_budget or monthly_budget <= 0:
        return 10  # neutral — no budget set
    ratio = estimated_cost / monthly_budget
    if ratio <= 0.7:
        return 20
    if ratio <= 0.9:
        return 15
    if ratio <= 1.0:
        return 10
    if ratio <= 1.2:
        return 5
    return 0


def _followup_score_from_overdue(overdue_followups: int) -> int:
    """Follow-up compliance score (15 pts)."""
    if overdue_followups == 0:
        return 15
    if overdue_followups <= 2:
        return 8
    return 0


def _build_result(client_id: int, client_name: str, comm: int, tasks: int,
                  digests: int, profit: int, followups: int) -> dict:
    """Assemble the health score dict from individual factor scores."""
    total = comm + tasks + digests + profit + followups
    total = max(0, min(100, total))
    if total >= 70:
        risk_level = "healthy"
    elif total >= 40:
        risk_level = "warning"
    else:
        risk_level = "at_risk"
    return {
        "client_id": client_id,
        "client_name": client_name,
        "score": total,
        "factors": {
            "communication": comm,
            "tasks": tasks,
            "digests": digests,
            "profitability": profit,
            "followups": followups,
        },
        "risk_level": risk_level,
    }


# ── Single-client version (used by /{client_id}/health) ─────


async def compute_health(client: Client, db: AsyncSession) -> dict:
    """Return health score dict for a single client."""
    now = datetime.now(timezone.utc)

    # --- 1. Communication frequency (25 pts) ---
    last_comm = await db.execute(
        select(func.max(CommunicationLog.occurred_at))
        .where(CommunicationLog.client_id == client.id)
    )
    last_comm_date = last_comm.scalar()
    if last_comm_date:
        if last_comm_date.tzinfo is None:
            last_comm_date = last_comm_date.replace(tzinfo=timezone.utc)
        days_since = (now - last_comm_date).days
    else:
        days_since = None
    comm_score = _comm_score_from_days(days_since)

    # --- 2. Task completion (25 pts) ---
    task_counts = await db.execute(
        select(Task.status, func.count())
        .where(Task.client_id == client.id)
        .group_by(Task.status)
    )
    task_map = dict(task_counts.all())
    total_tasks = sum(task_map.values())
    completed = task_map.get(TaskStatus.completed, 0)

    overdue = 0
    if total_tasks > 0:
        overdue_count_result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.client_id == client.id,
                Task.status != TaskStatus.completed,
                Task.due_date < now,
            )
        )
        overdue = overdue_count_result.scalar() or 0
    task_score = _task_score_from_counts(total_tasks, completed, overdue)

    # --- 3. Digest coverage (15 pts) ---
    four_weeks_ago = (now - timedelta(weeks=4)).date()
    digest_count_result = await db.execute(
        select(func.count()).select_from(WeeklyDigest).where(
            WeeklyDigest.client_id == client.id,
            WeeklyDigest.period_start >= four_weeks_ago,
        )
    )
    digest_count = digest_count_result.scalar() or 0
    digest_score = _digest_score_from_count(digest_count)

    # --- 4. Profitability (20 pts) ---
    if client.monthly_budget and client.monthly_budget > 0:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Use actual user hourly rates with fallback to DEFAULT_HOURLY_RATE
        cost_result = await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        TimeEntry.minutes
                        * func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE)
                        / 60
                    ),
                    0,
                )
            )
            .join(Task, TimeEntry.task_id == Task.id)
            .join(User, TimeEntry.user_id == User.id)
            .where(Task.client_id == client.id, TimeEntry.date >= month_start)
        )
        estimated_cost = float(cost_result.scalar() or 0)
    else:
        estimated_cost = 0
    profit_score = _profit_score_from_cost(client.monthly_budget, estimated_cost)

    # --- 5. Follow-up compliance (15 pts) ---
    pending_followups_result = await db.execute(
        select(func.count()).select_from(CommunicationLog).where(
            CommunicationLog.client_id == client.id,
            CommunicationLog.requires_followup == True,  # noqa: E712
            CommunicationLog.followup_date < now,
        )
    )
    overdue_followups = pending_followups_result.scalar() or 0
    followup_score = _followup_score_from_overdue(overdue_followups)

    return _build_result(
        client.id, client.name,
        comm_score, task_score, digest_score, profit_score, followup_score,
    )


# ── Batch version (used by /health-scores) ──────────────────


async def compute_health_batch(
    clients: List[Client], db: AsyncSession
) -> list[dict]:
    """Compute health scores for many clients using 6 batch queries
    instead of N*6 individual ones.  Returns identical results to
    calling compute_health per client.
    """
    if not clients:
        return []

    now = datetime.now(timezone.utc)
    client_ids = [c.id for c in clients]
    client_name_map = {c.id: c.name for c in clients}
    client_budget_map = {c.id: c.monthly_budget for c in clients}

    # --- 1. Last communication date per client ---
    last_comm_result = await db.execute(
        select(
            CommunicationLog.client_id,
            func.max(CommunicationLog.occurred_at),
        )
        .where(CommunicationLog.client_id.in_(client_ids))
        .group_by(CommunicationLog.client_id)
    )
    last_comm_map: dict[int, datetime | None] = dict(last_comm_result.all())

    # --- 2. Task counts by status per client ---
    task_counts_result = await db.execute(
        select(
            Task.client_id,
            Task.status,
            func.count(),
        )
        .where(Task.client_id.in_(client_ids))
        .group_by(Task.client_id, Task.status)
    )
    # Build nested dict: {client_id: {status: count}}
    task_status_map: dict[int, dict] = {}
    for cid, task_status, cnt in task_counts_result.all():
        task_status_map.setdefault(cid, {})[task_status] = cnt

    # --- 3. Overdue tasks per client ---
    overdue_result = await db.execute(
        select(
            Task.client_id,
            func.count(),
        )
        .where(
            Task.client_id.in_(client_ids),
            Task.status != TaskStatus.completed,
            Task.due_date < now,
        )
        .group_by(Task.client_id)
    )
    overdue_map: dict[int, int] = dict(overdue_result.all())

    # --- 4. Digest count per client (last 4 weeks) ---
    four_weeks_ago = (now - timedelta(weeks=4)).date()
    digest_result = await db.execute(
        select(
            WeeklyDigest.client_id,
            func.count(),
        )
        .where(
            WeeklyDigest.client_id.in_(client_ids),
            WeeklyDigest.period_start >= four_weeks_ago,
        )
        .group_by(WeeklyDigest.client_id)
    )
    digest_map: dict[int, int] = dict(digest_result.all())

    # --- 5. Estimated cost per client (this month) ---
    # Uses actual user hourly rates with fallback to DEFAULT_HOURLY_RATE
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cost_result = await db.execute(
        select(
            Task.client_id,
            func.coalesce(
                func.sum(
                    TimeEntry.minutes
                    * func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE)
                    / 60
                ),
                0,
            ),
        )
        .join(Task, TimeEntry.task_id == Task.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            Task.client_id.in_(client_ids),
            TimeEntry.date >= month_start,
        )
        .group_by(Task.client_id)
    )
    cost_map: dict[int, float] = {cid: float(v) for cid, v in cost_result.all()}

    # --- 6. Overdue follow-ups per client ---
    followup_result = await db.execute(
        select(
            CommunicationLog.client_id,
            func.count(),
        )
        .where(
            CommunicationLog.client_id.in_(client_ids),
            CommunicationLog.requires_followup == True,  # noqa: E712
            CommunicationLog.followup_date < now,
        )
        .group_by(CommunicationLog.client_id)
    )
    followup_map: dict[int, int] = dict(followup_result.all())

    # --- Assemble scores ---
    scores: list[dict] = []
    for cid in client_ids:
        # 1. Communication
        last_date = last_comm_map.get(cid)
        if last_date is not None:
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            days_since: int | None = (now - last_date).days
        else:
            days_since = None
        comm = _comm_score_from_days(days_since)

        # 2. Tasks
        status_counts = task_status_map.get(cid, {})
        total_tasks = sum(status_counts.values())
        completed = status_counts.get(TaskStatus.completed, 0)
        overdue = overdue_map.get(cid, 0)
        tasks = _task_score_from_counts(total_tasks, completed, overdue)

        # 3. Digests
        digests = _digest_score_from_count(digest_map.get(cid, 0))

        # 4. Profitability
        estimated_cost = cost_map.get(cid, 0.0)
        profit = _profit_score_from_cost(client_budget_map[cid], estimated_cost)

        # 5. Follow-ups
        followups = _followup_score_from_overdue(followup_map.get(cid, 0))

        scores.append(_build_result(
            cid, client_name_map[cid],
            comm, tasks, digests, profit, followups,
        ))

    return scores
