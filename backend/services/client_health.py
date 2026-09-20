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
from dataclasses import dataclass
from typing import List

from sqlalchemy import Date as SQLDate, cast, select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, CommunicationLog, Task, TaskStatus,
    WeeklyDigest, TimeEntry, User,
)
from backend.services.temporal import business_today
from backend.services.time_entry_dates import time_entry_civil_period


# ── Scoring helpers ──────────────────────────────────────────


@dataclass(frozen=True)
class HealthCapabilities:
    """Sources this caller can actually observe through the product."""

    communications: bool = True
    tasks: bool = True
    digests: bool = True
    profitability: bool = True


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


def _digest_score_from_count(digest_count: int) -> int | None:
    """A recent digest is positive evidence; absence has no meaning without cadence."""
    return 15 if digest_count > 0 else None


def _profit_score_from_cost(monthly_budget: float | None, estimated_cost: float) -> int:
    """Profitability score (20 pts)."""
    if not monthly_budget or float(monthly_budget) <= 0:
        return 10  # neutral — no budget set
    ratio = float(estimated_cost) / float(monthly_budget)
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


FACTOR_MAX = {
    "communication": 25,
    "tasks": 25,
    "digests": 15,
    "profitability": 20,
    "followups": 15,
}
FACTOR_SOURCE = {
    "communication": "communications",
    "tasks": "tasks",
    "digests": "digests",
    "profitability": "profitability",
    "followups": "communications",
}
MINIMUM_MEASURED_WEIGHT = 40
MINIMUM_SOURCE_COUNT = 2


def _build_result(
    client_id: int,
    client_name: str,
    factors: dict[str, int | None],
    observations: dict[str, str],
    risk_signals: list[str] | None = None,
) -> dict:
    """Normalize only measured factors; never turn missing sources into health."""
    available_weight = sum(
        FACTOR_MAX[name] for name, value in factors.items() if value is not None
    )
    available_sources = {
        FACTOR_SOURCE[name] for name, value in factors.items() if value is not None
    }
    enough_information = (
        available_weight >= MINIMUM_MEASURED_WEIGHT
        and len(available_sources) >= MINIMUM_SOURCE_COUNT
    )
    score = (
        round(sum(value for value in factors.values() if value is not None) * 100 / available_weight)
        if enough_information and available_weight
        else None
    )
    risk_signals = risk_signals or []
    if risk_signals:
        risk_level = "at_risk"
    elif score is None:
        risk_level = "no_data"
    elif score >= 70:
        risk_level = "healthy"
    elif score >= 40:
        risk_level = "warning"
    else:
        risk_level = "at_risk"
    return {
        "client_id": client_id,
        "client_name": client_name,
        "score": score,
        "factors": factors,
        "factor_max": FACTOR_MAX,
        "observations": observations,
        "available_weight": available_weight,
        "available_source_count": len(available_sources),
        "enough_information": enough_information,
        "risk_signals": risk_signals,
        "risk_level": risk_level,
    }


def _utc_now_naive() -> datetime:
    """Use naive UTC datetimes to match TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _observations(
    capabilities: HealthCapabilities, *, days_since: int | None,
    total_tasks: int, completed: int, overdue: int, digest_count: int,
    profitability_available: bool, estimated_cost: float, monthly_budget: float | None,
    overdue_followups: int,
) -> dict[str, str]:
    """Describe each measured source and its real decision window."""
    return {
        "communication": "Fuente no disponible" if not capabilities.communications else (
            f"Último contacto registrado: hace {days_since} días · riesgo a partir de 31 días"
            if days_since is not None else
            "Sin comunicaciones registradas · riesgo sólo tras 31 días desde un contacto registrado"
        ),
        "tasks": "Fuente no disponible" if not capabilities.tasks else (
            f"Histórico no retirado: {completed}/{total_tasks} completadas · {overdue} vencidas hoy"
            if total_tasks else "Histórico no retirado: sin tareas registradas"
        ),
        "digests": "Fuente no disponible" if not capabilities.digests else (
            f"Últimas 4 semanas: {digest_count} resúmenes · la ausencia no implica riesgo sin cadencia"
        ),
        "profitability": "Fuente no disponible" if not capabilities.profitability else (
            "Mes civil actual: presupuesto no configurado" if not profitability_available else
            f"Mes civil actual: coste estimado {estimated_cost:.0f} de presupuesto {monthly_budget:.0f}"
        ),
        "followups": "Fuente no disponible" if days_since is None else (
            f"Ahora: {overdue_followups} seguimientos vencidos"
        ),
    }


# ── Single-client version (used by /{client_id}/health) ─────


async def compute_health(
    client: Client,
    db: AsyncSession,
    capabilities: HealthCapabilities | None = None,
) -> dict:
    """Return health score dict for a single client."""
    capabilities = capabilities or HealthCapabilities()
    now = _utc_now_naive()

    # --- 1. Communication frequency (25 pts) ---
    last_comm_date = None
    if capabilities.communications:
        last_comm = await db.execute(
            select(func.max(CommunicationLog.occurred_at))
            .where(CommunicationLog.client_id == client.id)
        )
        last_comm_date = _as_naive_utc(last_comm.scalar())
    if last_comm_date:
        days_since = (now - last_comm_date).days
    else:
        days_since = None
    comm_score = _comm_score_from_days(days_since) if days_since is not None else None

    # --- 2. Task completion (25 pts) ---
    task_map = {}
    if capabilities.tasks:
        task_counts = await db.execute(
            select(Task.status, func.count())
            .where(Task.client_id == client.id, Task.retired_at.is_(None))
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
                Task.retired_at.is_(None),
                Task.status != TaskStatus.completed,
                cast(Task.due_date, SQLDate) < business_today(),
            )
        )
        overdue = overdue_count_result.scalar() or 0
    task_score = _task_score_from_counts(total_tasks, completed, overdue) if total_tasks else None

    # --- 3. Digest coverage (15 pts) ---
    four_weeks_ago = (now - timedelta(weeks=4)).date()
    digest_count = 0
    if capabilities.digests:
        digest_count_result = await db.execute(
            select(func.count()).select_from(WeeklyDigest).where(
                WeeklyDigest.client_id == client.id,
                WeeklyDigest.period_start >= four_weeks_ago,
            )
        )
        digest_count = digest_count_result.scalar() or 0
    digest_score = _digest_score_from_count(digest_count) if capabilities.digests else None

    # --- 4. Profitability (20 pts) ---
    if capabilities.profitability and client.monthly_budget and float(client.monthly_budget) > 0:
        month_start = business_today().replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
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
            .where(
                Task.client_id == client.id,
                time_entry_civil_period(month_start, next_month),
            )
        )
        estimated_cost = float(cost_result.scalar() or 0)
    else:
        estimated_cost = 0
    profitability_available = (
        capabilities.profitability
        and client.monthly_budget is not None
        and float(client.monthly_budget) > 0
    )
    profit_score = (
        _profit_score_from_cost(float(client.monthly_budget), estimated_cost)
        if profitability_available else None
    )

    # --- 5. Follow-up compliance (15 pts) ---
    overdue_followups = 0
    if capabilities.communications and last_comm_date is not None:
        pending_followups_result = await db.execute(
            select(func.count()).select_from(CommunicationLog).where(
                CommunicationLog.client_id == client.id,
                CommunicationLog.requires_followup == True,  # noqa: E712
                CommunicationLog.followup_date < now,
            )
        )
        overdue_followups = pending_followups_result.scalar() or 0
    followup_score = _followup_score_from_overdue(overdue_followups) if last_comm_date is not None else None

    risk_signals = []
    if days_since is not None and days_since > 30:
        risk_signals.append(f"Último contacto hace {days_since} días")
    if overdue >= 2:
        risk_signals.append(f"{overdue} tareas vencidas")
    if profitability_available and profit_score == 0:
        risk_signals.append("El coste estimado supera el presupuesto en más de un 20 %")
    if overdue_followups > 2:
        risk_signals.append(f"{overdue_followups} seguimientos vencidos")

    return _build_result(client.id, client.name, {
        "communication": comm_score,
        "tasks": task_score,
        "digests": digest_score,
        "profitability": profit_score,
        "followups": followup_score,
    }, _observations(
        capabilities, days_since=days_since, total_tasks=total_tasks,
        completed=completed, overdue=overdue, digest_count=digest_count,
        profitability_available=profitability_available, estimated_cost=estimated_cost,
        monthly_budget=float(client.monthly_budget) if client.monthly_budget is not None else None,
        overdue_followups=overdue_followups,
    ), risk_signals)


# ── Batch version (used by /health-scores) ──────────────────


async def compute_health_batch(
    clients: List[Client], db: AsyncSession,
    capabilities: HealthCapabilities | None = None,
) -> list[dict]:
    """Compute health scores for many clients using 6 batch queries
    instead of N*6 individual ones.  Returns identical results to
    calling compute_health per client.
    """
    capabilities = capabilities or HealthCapabilities()
    if not clients:
        return []

    now = _utc_now_naive()
    client_ids = [c.id for c in clients]
    client_name_map = {c.id: c.name for c in clients}
    client_budget_map = {c.id: float(c.monthly_budget) if c.monthly_budget is not None else None for c in clients}

    # --- 1. Last communication date per client ---
    last_comm_map: dict[int, datetime | None] = {}
    if capabilities.communications:
        last_comm_result = await db.execute(
            select(
                CommunicationLog.client_id,
                func.max(CommunicationLog.occurred_at),
            )
            .where(CommunicationLog.client_id.in_(client_ids))
            .group_by(CommunicationLog.client_id)
        )
        last_comm_map = dict(last_comm_result.all())

    # --- 2. Task counts by status per client ---
    task_status_map: dict[int, dict] = {}
    if capabilities.tasks:
        task_counts_result = await db.execute(
            select(
                Task.client_id,
                Task.status,
                func.count(),
            )
            .where(Task.client_id.in_(client_ids), Task.retired_at.is_(None))
            .group_by(Task.client_id, Task.status)
        )
        for cid, task_status, cnt in task_counts_result.all():
            task_status_map.setdefault(cid, {})[task_status] = cnt

    # --- 3. Overdue tasks per client ---
    overdue_map: dict[int, int] = {}
    if capabilities.tasks:
        overdue_result = await db.execute(
            select(
                Task.client_id,
                func.count(),
            )
            .where(
                Task.client_id.in_(client_ids),
                Task.retired_at.is_(None),
                Task.status != TaskStatus.completed,
                cast(Task.due_date, SQLDate) < business_today(),
            )
            .group_by(Task.client_id)
        )
        overdue_map = dict(overdue_result.all())

    # --- 4. Digest count per client (last 4 weeks) ---
    four_weeks_ago = (now - timedelta(weeks=4)).date()
    digest_map: dict[int, int] = {}
    if capabilities.digests:
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
        digest_map = dict(digest_result.all())

    # --- 5. Estimated cost per client (this month) ---
    # Uses actual user hourly rates with fallback to DEFAULT_HOURLY_RATE
    month_start = business_today().replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    cost_map: dict[int, float] = {}
    if capabilities.profitability and any(client_budget_map.values()):
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
            .select_from(TimeEntry)
            .join(Task, TimeEntry.task_id == Task.id)
            .join(User, TimeEntry.user_id == User.id)
            .where(
                Task.client_id.in_(client_ids),
                time_entry_civil_period(month_start, next_month),
            )
            .group_by(Task.client_id)
        )
        cost_map = {cid: float(v) for cid, v in cost_result.all()}

    # --- 6. Overdue follow-ups per client ---
    followup_map: dict[int, int] = {}
    if capabilities.communications and last_comm_map:
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
        followup_map = dict(followup_result.all())

    # --- Assemble scores ---
    scores: list[dict] = []
    for cid in client_ids:
        # 1. Communication
        last_date = _as_naive_utc(last_comm_map.get(cid))
        if last_date is not None:
            days_since: int | None = (now - last_date).days
        else:
            days_since = None
        comm = _comm_score_from_days(days_since) if days_since is not None else None

        # 2. Tasks
        status_counts = task_status_map.get(cid, {})
        total_tasks = sum(status_counts.values())
        completed = status_counts.get(TaskStatus.completed, 0)
        overdue = overdue_map.get(cid, 0)
        tasks = _task_score_from_counts(total_tasks, completed, overdue) if total_tasks else None

        # 3. Digests
        digest_count = digest_map.get(cid, 0)
        digests = _digest_score_from_count(digest_count) if capabilities.digests else None

        # 4. Profitability
        estimated_cost = cost_map.get(cid, 0.0)
        profitability_available = capabilities.profitability and bool(client_budget_map[cid] and client_budget_map[cid] > 0)
        profit = _profit_score_from_cost(client_budget_map[cid], estimated_cost) if profitability_available else None

        # 5. Follow-ups
        overdue_followups = followup_map.get(cid, 0)
        followups = _followup_score_from_overdue(overdue_followups) if last_date is not None else None

        risk_signals = []
        if days_since is not None and days_since > 30:
            risk_signals.append(f"Último contacto hace {days_since} días")
        if overdue >= 2:
            risk_signals.append(f"{overdue} tareas vencidas")
        if profitability_available and profit == 0:
            risk_signals.append("El coste estimado supera el presupuesto en más de un 20 %")
        if overdue_followups > 2:
            risk_signals.append(f"{overdue_followups} seguimientos vencidos")

        scores.append(_build_result(cid, client_name_map[cid], {
            "communication": comm,
            "tasks": tasks,
            "digests": digests,
            "profitability": profit,
            "followups": followups,
        }, _observations(
            capabilities, days_since=days_since, total_tasks=total_tasks,
            completed=completed, overdue=overdue, digest_count=digest_count,
            profitability_available=profitability_available, estimated_cost=estimated_cost,
            monthly_budget=client_budget_map[cid], overdue_followups=overdue_followups,
        ), risk_signals))

    return scores
