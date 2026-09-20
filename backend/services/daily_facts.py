from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import Date, and_, cast, or_, select

from backend.core.modules import is_enabled
from backend.db.models import (
    Client,
    Project,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserPermission,
    UserRole,
)
from backend.schemas.daily_fact import DailyFact, DailyFacts
from backend.services.temporal import civil_day_utc_bounds
from backend.services.time_entry_dates import (
    time_entry_business_date,
    time_entry_civil_period,
)


async def _access(db, actor) -> tuple[int, bool, bool] | None:
    actor_id = actor if isinstance(actor, int) else actor.id
    row = (
        await db.execute(
            select(User.id, User.role, User.is_active).where(User.id == actor_id)
        )
    ).one_or_none()
    if not row or not row.is_active:
        return None
    if row.role == UserRole.admin:
        return actor_id, is_enabled("tasks"), is_enabled("timesheet")
    modules = set(
        (
            await db.execute(
                select(UserPermission.module).where(
                    UserPermission.user_id == actor_id,
                    UserPermission.can_read.is_(True),
                )
            )
        ).scalars()
    )
    return (
        actor_id,
        is_enabled("tasks") and "tasks" in modules,
        is_enabled("timesheet") and "timesheet" in modules,
    )


def _fact(kind, row, *, key, minutes=None, detail=None, allow_task_link=True):
    def serialized(name):
        value = getattr(row, name, None)
        return value.isoformat() if hasattr(value, "isoformat") else value

    canonical = {
        "kind": kind,
        "task_id": row.task_id,
        "title": row.title or "Trabajo sin tarea",
        "client_id": row.client_id,
        "client_name": row.client_name,
        "project_id": row.project_id,
        "project_name": row.project_name,
        "minutes": minutes,
        "detail": detail,
        "date": serialized("date"),
        "started_at": serialized("started_at"),
        "completed_at": serialized("completed_at"),
        "advanced_at": serialized("advanced_at"),
        "waiting_for": serialized("waiting_for"),
        "follow_up_date": serialized("follow_up_date"),
        "scheduled_date": serialized("scheduled_date"),
        "due_date": serialized("due_date"),
    }
    version = hashlib.sha256(
        json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()[:16]
    return DailyFact(
        key=f"{key}:{version}",
        kind=kind,
        task_id=row.task_id,
        title=row.title or "Trabajo sin tarea",
        client_id=row.client_id,
        client_name=row.client_name,
        project_id=row.project_id,
        project_name=row.project_name,
        minutes=minutes,
        href=f"/tasks?task={row.task_id}" if row.task_id and allow_task_link else None,
        detail=detail,
    )


async def collect_daily_facts(db, actor, day: date) -> dict:
    """Collect every canonical fact with a constant number of SQL statements."""
    access = await _access(db, actor)
    if access is None:
        return DailyFacts(
            date=day,
            text="",
            completed_count=0,
            worked_on_count=0,
            total_minutes=0,
            facts=[],
        ).model_dump(mode="json")
    user_id, tasks_read, timesheet_read = access
    facts: list[DailyFact] = []
    tomorrow = day + timedelta(days=1)

    if tasks_read:
        start, end = civil_day_utc_bounds(day)
        task_rows = (
            await db.execute(
                select(
                    Task.id.label("task_id"),
                    Task.title,
                    Task.client_id,
                    Client.name.label("client_name"),
                    Task.project_id,
                    Project.name.label("project_name"),
                    Task.status,
                    Task.completed_at,
                    Task.advanced_at,
                    Task.is_recurring,
                    Task.waiting_for,
                    Task.follow_up_date,
                    Task.scheduled_date,
                    Task.due_date,
                )
                .outerjoin(Client, Client.id == Task.client_id)
                .outerjoin(Project, Project.id == Task.project_id)
                .where(
                    Task.assigned_to == user_id,
                    or_(
                        and_(
                            Task.status == TaskStatus.completed,
                            Task.completed_at >= start,
                            Task.completed_at < end,
                        ),
                        and_(
                            Task.retired_at.is_(None),
                            Task.status == TaskStatus.advanced,
                            Task.advanced_at == day,
                        ),
                        and_(
                            Task.retired_at.is_(None),
                            Task.status == TaskStatus.waiting,
                            Task.waiting_for.is_not(None),
                            Task.waiting_for != "",
                        ),
                        and_(
                            Task.retired_at.is_(None),
                            Task.status.notin_(
                                (
                                    TaskStatus.completed,
                                    TaskStatus.waiting,
                                    TaskStatus.backlog,
                                )
                            ),
                            Task.is_recurring.is_(False),
                            or_(
                                Task.scheduled_date <= tomorrow,
                                cast(Task.due_date, Date) <= tomorrow,
                            ),
                        ),
                    ),
                )
                .order_by(Task.id)
            )
        ).all()
        for row in task_rows:
            if (
                row.status == TaskStatus.completed
                and row.completed_at
                and start <= row.completed_at < end
            ):
                facts.append(
                    _fact(
                        "task_completed",
                        row,
                        key=f"task_completed:{row.task_id}:{row.completed_at.isoformat()}",
                        detail="Completada; responsable actual",
                    )
                )
            if row.status == TaskStatus.advanced and row.advanced_at == day:
                facts.append(
                    _fact(
                        "task_advanced",
                        row,
                        key=f"task_advanced:{row.task_id}:{day.isoformat()}",
                        detail="Marcada como avanzada hoy",
                    )
                )
            if row.status == TaskStatus.waiting and row.waiting_for:
                suffix = (
                    f"; revisar {row.follow_up_date.isoformat()}"
                    if row.follow_up_date
                    else ""
                )
                facts.append(
                    _fact(
                        "task_waiting",
                        row,
                        key=f"task_waiting:{row.task_id}:{row.follow_up_date.isoformat() if row.follow_up_date else 'open'}",
                        detail=f"En espera de {row.waiting_for}{suffix}",
                    )
                )
            if (
                row.status
                not in (TaskStatus.completed, TaskStatus.waiting, TaskStatus.backlog)
                and not row.is_recurring
                and not row.scheduled_date is None
            ):
                if row.scheduled_date < day:
                    facts.append(
                        _fact(
                            "next_step",
                            row,
                            key=f"next_step:{row.task_id}:{row.scheduled_date.isoformat()}",
                            detail=f"Pendiente desde {row.scheduled_date.isoformat()}",
                        )
                    )
                elif row.scheduled_date == tomorrow:
                    facts.append(
                        _fact(
                            "next_step",
                            row,
                            key=f"next_step:{row.task_id}:{tomorrow.isoformat()}",
                            detail=f"Planificada para {tomorrow.isoformat()}",
                        )
                    )
            elif (
                row.status
                not in (TaskStatus.completed, TaskStatus.waiting, TaskStatus.backlog)
                and not row.is_recurring
                and row.due_date
                and row.due_date.date() <= tomorrow
            ):
                due = row.due_date.date()
                facts.append(
                    _fact(
                        "next_step",
                        row,
                        key=f"next_step:{row.task_id}:{due.isoformat()}",
                        detail=(
                            f"Vence {tomorrow.isoformat()}"
                            if due == tomorrow
                            else f"Pendiente desde vencimiento {due.isoformat()}"
                        ),
                    )
                )

    if timesheet_read:
        time_rows = (
            await db.execute(
                select(
                    TimeEntry.id.label("entry_id"),
                    TimeEntry.task_id,
                    TimeEntry.minutes,
                    TimeEntry.date,
                    TimeEntry.started_at,
                    Task.title,
                    Task.client_id,
                    Client.name.label("client_name"),
                    Task.project_id,
                    Project.name.label("project_name"),
                )
                .outerjoin(Task, Task.id == TimeEntry.task_id)
                .outerjoin(Client, Client.id == Task.client_id)
                .outerjoin(Project, Project.id == Task.project_id)
                .where(
                    TimeEntry.user_id == user_id,
                    TimeEntry.minutes.is_not(None),
                    time_entry_civil_period(day, day + timedelta(days=1)),
                )
                .order_by(TimeEntry.id)
            )
        ).all()
        for row in time_rows:
            civil = time_entry_business_date(row.date, row.started_at)
            facts.append(
                _fact(
                    "time_logged",
                    row,
                    key=f"time_logged:{row.entry_id}",
                    minutes=int(row.minutes),
                    detail=f"{int(row.minutes)} min registrados el {civil.isoformat()}",
                    allow_task_link=tasks_read,
                )
            )

    order = {
        "task_completed": 0,
        "time_logged": 1,
        "task_advanced": 2,
        "task_waiting": 3,
        "next_step": 4,
    }
    facts.sort(
        key=lambda fact: (
            fact.client_name or "",
            fact.project_name or "",
            order[fact.kind],
            fact.task_id or 0,
            fact.key,
        )
    )
    lines: list[str] = []
    current_group = None
    for fact in facts:
        group = (
            " · ".join(filter(None, (fact.client_name, fact.project_name))) or "General"
        )
        if group != current_group:
            if lines:
                lines.append("")
            lines.append(f"**{group}**")
            current_group = group
        marker = {
            "task_completed": "✅",
            "time_logged": "⏱",
            "task_advanced": "🔄",
            "task_waiting": "⏸",
            "next_step": "➡️",
        }[fact.kind]
        suffix = f" ({fact.minutes} min)" if fact.minutes is not None else ""
        detail = f" — {fact.detail}" if fact.detail else ""
        lines.append(f"- {marker} {fact.title}{suffix}{detail}")
    worked_ids = {
        f.task_id
        for f in facts
        if f.kind in ("time_logged", "task_advanced") and f.task_id is not None
    }
    return DailyFacts(
        date=day,
        text="\n".join(lines),
        completed_count=sum(f.kind == "task_completed" for f in facts),
        worked_on_count=len(worked_ids),
        total_minutes=sum(f.minutes or 0 for f in facts if f.kind == "time_logged"),
        facts=facts,
    ).model_dump(mode="json")


async def validate_daily_fact_selection(
    db, actor, day: date, keys: list[str]
) -> list[dict]:
    """Return canonical snapshots in requested order, rejecting stale/foreign keys."""
    if len(keys) != len(set(keys)):
        raise ValueError("source_fact_keys contains duplicates")
    available = {
        fact["key"]: fact
        for fact in (await collect_daily_facts(db, actor, day))["facts"]
    }
    unknown = [key for key in keys if key not in available]
    if unknown:
        raise ValueError(f"Unknown or unavailable source facts: {', '.join(unknown)}")
    return [available[key] for key in keys]
