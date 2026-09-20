"""Weekly report facts and Discord renderers with a strict finance boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import Date, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    IN_PROGRESS_TASK_STATUSES,
    Client,
    ClientStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
)
from backend.services.temporal import business_today, civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period
from backend.startup.background_tasks import _is_qa_user

SAMPLE_LIMIT = 15


@dataclass(frozen=True)
class WeeklyMember:
    user_id: int
    name: str
    minutes: int
    capacity_minutes: int | None
    active: bool


@dataclass(frozen=True)
class WeeklyClient:
    client_id: int | None
    name: str
    minutes: int


@dataclass(frozen=True)
class WeeklyTask:
    task_id: int
    title: str
    client_id: int | None
    client_name: str
    assignee_name: str | None
    due_date: date | None = None


@dataclass(frozen=True)
class WeeklyFinancialClient:
    client_id: int | None
    name: str
    cost: float


@dataclass(frozen=True)
class WeeklyReportFacts:
    period_start: date
    period_end: date
    snapshot_date: date
    completed_count: int
    in_progress_count: int
    pending_count: int
    overdue_count: int
    total_minutes: int
    capacity_minutes: int
    members: tuple[WeeklyMember, ...]
    clients: tuple[WeeklyClient, ...]
    inactive_client_names: tuple[str, ...]
    completed: tuple[WeeklyTask, ...]
    in_progress: tuple[WeeklyTask, ...]
    overdue: tuple[WeeklyTask, ...]
    upcoming_count: int
    upcoming: tuple[WeeklyTask, ...]
    financial_clients: tuple[WeeklyFinancialClient, ...] = field(default_factory=tuple)


def _fmt_h(minutes: float) -> str:
    hours = minutes / 60.0
    return f"{int(hours)}h" if hours == int(hours) else f"{hours:.1f}h"


def _is_qa(row) -> bool:
    return _is_qa_user(
        SimpleNamespace(
            full_name=row.full_name, short_name=row.short_name, email=row.email
        )
    )


def _task(row) -> WeeklyTask:
    due = (
        row.due_date.date()
        if row.due_date is not None and hasattr(row.due_date, "date")
        else row.due_date
    )
    return WeeklyTask(
        row.id,
        row.title,
        row.client_id,
        row.client_name or "Sin cliente",
        row.assignee_name,
        due,
    )


async def collect_weekly_report_facts(
    db: AsyncSession,
    *,
    period_start: date,
    period_end: date,
    include_financial: bool = False,
) -> WeeklyReportFacts:
    """Collect one inclusive civil week; current work is labelled separately."""
    if period_end < period_start:
        raise ValueError("Invalid report period")
    start_dt, _ = civil_day_utc_bounds(period_start)
    end_dt, _ = civil_day_utc_bounds(period_end + timedelta(days=1))
    snapshot = business_today()

    user_rows = (
        await db.execute(
            select(
                User.id,
                User.full_name,
                User.short_name,
                User.email,
                User.is_active,
                User.weekly_hours,
            ).order_by(User.id)
        )
    ).all()
    users = {row.id: row for row in user_rows if not _is_qa(row)}
    qa_ids = {row.id for row in user_rows if row.id not in users}

    time_query = (
        select(
            TimeEntry.user_id,
            Task.client_id,
            Client.name.label("client_name"),
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("minutes"),
        )
        .select_from(TimeEntry)
        .outerjoin(Task, TimeEntry.task_id == Task.id)
        .outerjoin(Client, Task.client_id == Client.id)
        .where(
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(period_start, period_end + timedelta(days=1)),
        )
        .group_by(TimeEntry.user_id, Task.client_id, Client.name)
    )
    if qa_ids:
        time_query = time_query.where(TimeEntry.user_id.notin_(qa_ids))
    time_rows = (await db.execute(time_query)).all()

    by_user: dict[int, int] = {}
    by_client: dict[int | None, WeeklyClient] = {}
    for row in time_rows:
        minutes = int(row.minutes or 0)
        by_user[row.user_id] = by_user.get(row.user_id, 0) + minutes
        old = by_client.get(row.client_id)
        by_client[row.client_id] = WeeklyClient(
            row.client_id,
            row.client_name or "Sin cliente",
            minutes + (old.minutes if old else 0),
        )

    members: list[WeeklyMember] = []
    active_user_ids = {user_id for user_id, user in users.items() if user.is_active}
    for user_id in sorted(active_user_ids | set(by_user)):
        user = users.get(user_id)
        if user is None:
            members.append(
                WeeklyMember(
                    user_id, f"Usuario #{user_id}", by_user.get(user_id, 0), None, False
                )
            )
            continue
        active = bool(user.is_active)
        capacity = (
            int(user.weekly_hours * 60)
            if active and user.weekly_hours is not None
            else (2400 if active else None)
        )
        members.append(
            WeeklyMember(
                user_id,
                user.short_name or user.full_name,
                by_user.get(user_id, 0),
                capacity,
                active,
            )
        )

    non_qa_assignee = (
        or_(Task.assigned_to.is_(None), Task.assigned_to.notin_(qa_ids))
        if qa_ids
        else True
    )
    operational = and_(
        Task.retired_at.is_(None),
        Task.is_recurring.is_(False),
        non_qa_assignee,
    )
    columns = (
        Task.id,
        Task.title,
        Task.client_id,
        Client.name.label("client_name"),
        func.coalesce(User.short_name, User.full_name).label("assignee_name"),
        Task.due_date,
    )

    def task_select():
        return (
            select(*columns)
            .outerjoin(Client, Task.client_id == Client.id)
            .outerjoin(User, Task.assigned_to == User.id)
        )

    async def count(where) -> int:
        return int((await db.scalar(select(func.count(Task.id)).where(where))) or 0)

    completed_filter = and_(
        Task.status == TaskStatus.completed,
        Task.completed_at >= start_dt,
        Task.completed_at < end_dt,
        Task.is_recurring.is_(False),
        non_qa_assignee,
    )
    completed_count = await count(completed_filter)
    completed = (
        await db.execute(
            task_select()
            .where(completed_filter)
            .order_by(Task.completed_at.desc(), Task.id)
            .limit(SAMPLE_LIMIT)
        )
    ).all()
    progress_filter = and_(operational, Task.status.in_(IN_PROGRESS_TASK_STATUSES))
    progress_count = await count(progress_filter)
    progress = (
        await db.execute(
            task_select()
            .where(progress_filter)
            .order_by(Task.due_date.asc().nulls_last(), Task.id)
            .limit(SAMPLE_LIMIT)
        )
    ).all()
    pending_filter = and_(operational, Task.status == TaskStatus.pending)
    pending_count = await count(pending_filter)
    overdue_filter = and_(
        operational,
        Task.status != TaskStatus.completed,
        Task.due_date.isnot(None),
        cast(Task.due_date, Date) < snapshot,
    )
    overdue_count = await count(overdue_filter)
    overdue = (
        await db.execute(
            task_select()
            .where(overdue_filter)
            .order_by(Task.due_date, Task.id)
            .limit(SAMPLE_LIMIT)
        )
    ).all()
    upcoming_filter = and_(
        pending_filter, Task.due_date.isnot(None), cast(Task.due_date, Date) >= snapshot
    )
    upcoming_count = await count(upcoming_filter)
    upcoming = (
        await db.execute(
            task_select()
            .where(upcoming_filter)
            .order_by(Task.due_date, Task.id)
            .limit(SAMPLE_LIMIT)
        )
    ).all()

    active_clients = (
        await db.execute(
            select(Client.id, Client.name)
            .where(Client.status == ClientStatus.active)
            .order_by(Client.id)
        )
    ).all()
    no_activity = tuple(row.name for row in active_clients if row.id not in by_client)

    financial: tuple[WeeklyFinancialClient, ...] = ()
    if include_financial:
        rate = func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE)
        finance_query = (
            select(
                Task.client_id,
                Client.name.label("client_name"),
                func.coalesce(func.sum(TimeEntry.minutes * rate / 60), 0).label("cost"),
            )
            .select_from(TimeEntry)
            .join(User, TimeEntry.user_id == User.id)
            .outerjoin(Task, TimeEntry.task_id == Task.id)
            .outerjoin(Client, Task.client_id == Client.id)
            .where(
                TimeEntry.minutes.isnot(None),
                time_entry_civil_period(period_start, period_end + timedelta(days=1)),
            )
            .group_by(Task.client_id, Client.name)
            .order_by(Task.client_id.asc().nulls_first())
        )
        if qa_ids:
            finance_query = finance_query.where(TimeEntry.user_id.notin_(qa_ids))
        financial = tuple(
            WeeklyFinancialClient(
                row.client_id,
                row.client_name or "Sin cliente",
                round(float(row.cost or 0), 2),
            )
            for row in (await db.execute(finance_query)).all()
        )

    return WeeklyReportFacts(
        period_start,
        period_end,
        snapshot,
        completed_count,
        progress_count,
        pending_count,
        overdue_count,
        sum(by_user.values()),
        sum(member.capacity_minutes or 0 for member in members if member.active),
        tuple(members),
        tuple(
            sorted(
                by_client.values(),
                key=lambda item: (-item.minutes, item.client_id or 0),
            )
        ),
        no_activity,
        tuple(map(_task, completed)),
        tuple(map(_task, progress)),
        tuple(map(_task, overdue)),
        upcoming_count,
        tuple(map(_task, upcoming)),
        financial,
    )


def render_weekly_operational(facts: WeeklyReportFacts) -> str:
    lines = [
        f"📊 **Repaso semanal operativo — {facts.period_start:%d/%m} al {facts.period_end:%d/%m/%Y}**",
        "",
    ]
    lines.extend(
        [
            f"⏱️ **Tiempo registrado en el período:** {_fmt_h(facts.total_minutes)}",
            f"📐 **Capacidad semanal actual del equipo activo:** {_fmt_h(facts.capacity_minutes)}",
        ]
    )
    lines += [
        f"✅ **Completadas en el período:** {facts.completed_count}",
        "_Solo se atribuyen al período las tareas con fecha de finalización registrada._",
        f"🔄 **En progreso ahora:** {facts.in_progress_count}",
        f"📋 **Pendientes:** {facts.pending_count} (estado actual)",
        f"🔴 **Vencidas ahora:** {facts.overdue_count}",
        "",
        "👥 **Tiempo del período por persona:**",
    ]
    for member in facts.members:
        if member.capacity_minutes is None:
            lines.append(
                f"  • {member.name}: {_fmt_h(member.minutes)} (persona inactiva; actividad histórica)"
            )
        elif member.capacity_minutes == 0:
            lines.append(
                f"  • {member.name}: {_fmt_h(member.minutes)} "
                "(capacidad semanal actual configurada: 0h)"
            )
        else:
            pct = member.minutes / member.capacity_minutes * 100
            bar = "🟩" if pct >= 80 else ("🟨" if pct >= 50 else "🟥")
            lines.append(
                f"  {bar} {member.name}: {_fmt_h(member.minutes)} / {_fmt_h(member.capacity_minutes)} "
                f"({pct:.0f}% de su capacidad semanal actual)"
            )
    lines.append("")

    def tasks(
        title: str, rows: tuple[WeeklyTask, ...], total: int, due_prefix: str = "vence"
    ):
        if not rows:
            return
        lines.append(f"{title} (muestra {len(rows)} de {total}):**")
        for task in rows:
            who = f" → {task.assignee_name}" if task.assignee_name else ""
            due = f" ({due_prefix} {task.due_date:%d/%m})" if task.due_date else ""
            lines.append(f"  • [{task.client_name}] {task.title}{who}{due}")
        lines.append("")

    tasks("✅ **Completado en el período", facts.completed, facts.completed_count)
    tasks("🔄 **En progreso ahora", facts.in_progress, facts.in_progress_count)
    if facts.clients or facts.inactive_client_names:
        lines.append("🏢 **Tiempo del período por cliente:**")
        for client in facts.clients:
            pct = (
                client.minutes / facts.total_minutes * 100 if facts.total_minutes else 0
            )
            lines.append(
                f"  • {client.name}: {_fmt_h(client.minutes)} ({pct:.0f}%){' ⚠️' if pct > 40 else ''}"
            )
        if facts.inactive_client_names:
            lines.append(
                f"  💤 Sin actividad: {', '.join(facts.inactive_client_names)}"
            )
        lines.append("")
    tasks("🔴 **Vencidas ahora", facts.overdue, facts.overdue_count, "vencía")
    if facts.upcoming:
        lines.append(
            f"📋 **Próximas pendientes desde {facts.snapshot_date:%d/%m} "
            f"(muestra {len(facts.upcoming)} de {facts.upcoming_count}):**"
        )
        for task in facts.upcoming:
            who = f" → {task.assignee_name}" if task.assignee_name else ""
            lines.append(
                f"  • [{task.client_name}] {task.title}{who} (vence {task.due_date:%d/%m})"
            )
        lines.append("")
    lines.append("💪 ¡Buen finde!")
    return "\n".join(lines)


def render_weekly_financial(facts: WeeklyReportFacts) -> str:
    if not facts.financial_clients:
        return ""
    lines = [
        f"💶 **Coste interno — {facts.period_start:%d/%m} al {facts.period_end:%d/%m/%Y}**",
        "Contenido financiero para administración.",
    ]
    lines += [
        f"  • {client.name}: {client.cost:.0f}€" for client in facts.financial_clients
    ]
    return "\n".join(lines)


async def generate_weekly_report(
    db: AsyncSession,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    include_financial: bool = False,
) -> str:
    """Render the existing weekly delivery; operational by default."""
    today = business_today()
    ws = period_start or today - timedelta(days=today.weekday())
    we = period_end or ws + timedelta(days=6)
    facts = await collect_weekly_report_facts(
        db, period_start=ws, period_end=we, include_financial=include_financial
    )
    operational = render_weekly_operational(facts)
    financial = render_weekly_financial(facts) if include_financial else ""
    return f"{operational}\n\n{financial}" if financial else operational
