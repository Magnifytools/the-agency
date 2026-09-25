"""Daily reminders service — morning plan & evening recap via Discord."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select, func, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    IN_PROGRESS_TASK_STATUSES,
    Task, TaskStatus, TaskPriority, TimeEntry, DailyUpdate,
    CompanyHoliday, User, UserRole, UserPermission, Event, EventType,
)
import re

from backend.services.discord import send_to_discord
from backend.services.temporal import business_today, civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period

logger = logging.getLogger(__name__)

# Strip monetary amounts from task titles shown in shared channels
_MONEY_RE = re.compile(r"\s*\(?\s*[\d.,]+\s*€\s*\)?|\s*\(?\s*€\s*[\d.,]+\s*\)?", re.IGNORECASE)

# Priority display order and emoji mapping
_PRIORITY_ORDER = {
    TaskPriority.urgent: (0, "\U0001f534"),   # red circle
    TaskPriority.high: (1, "\U0001f7e0"),      # orange circle
    TaskPriority.medium: (2, "\U0001f7e1"),    # yellow circle
    TaskPriority.low: (3, "\u26aa"),           # white circle
}


async def is_working_day(db: AsyncSession, day: date, region: str | None) -> bool:
    """Return False for weekends and company holidays."""
    if day.weekday() >= 5:
        return False

    stmt = select(CompanyHoliday.id).where(
        CompanyHoliday.date == day,
        (CompanyHoliday.region.is_(None)) | (CompanyHoliday.region == region),
    ).limit(1)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return False

    return True


def _morning_sections(today: date):
    """The same mutually exclusive Hoy buckets for personal and shared plans."""
    due_day = func.date(Task.due_date)
    actionable = Task.status != TaskStatus.waiting
    return (
        ("Para hoy", actionable & or_(
            due_day == today,
            (Task.scheduled_date == today) & or_(Task.due_date.is_(None), due_day > today),
        )),
        ("Arrastre pendiente", actionable & or_(
            due_day < today,
            (Task.scheduled_date < today) & or_(Task.due_date.is_(None), due_day != today),
        )),
        ("Sin planificar", actionable & Task.scheduled_date.is_(None) & or_(
            Task.due_date.is_(None), due_day > today,
        )),
        ("En espera (no son acciones inmediatas)", (Task.status == TaskStatus.waiting) & (due_day <= today)),
    )


def _morning_priority_sort():
    return case({TaskPriority.urgent: 0, TaskPriority.high: 1,
                 TaskPriority.medium: 2, TaskPriority.low: 3}, value=Task.priority, else_=4)


def _morning_task_line(task: Task, today: date, *, mark_unassigned: bool) -> str:
    _, emoji = _PRIORITY_ORDER.get(task.priority, (4, "\u26aa"))
    parts = [emoji]
    if task.priority == TaskPriority.urgent:
        parts.append("[URGENTE]")
    parts.append(_MONEY_RE.sub("", task.title).strip())
    if mark_unassigned and task.assigned_to is None:
        parts.append("(sin responsable)")
    if task.status == TaskStatus.backlog:
        parts.append("(por priorizar)")
    elif task.status == TaskStatus.in_review:
        parts.append("(en revisión)")
    if task.client:
        parts.append(f"\u2014 {task.client.name}")
    if task.due_date:
        task_due_day = task.due_date.date()
        if task_due_day < today:
            parts.append("(vencida)")
        elif task_due_day == today:
            parts.append("(vence hoy)")
        else:
            parts.append(f"(vence {task_due_day:%d/%m})")
    return " ".join(parts)


async def generate_team_morning_plan(db: AsyncSession, day: date) -> str:
    """One shared agenda, grouped by active task readers; unassigned work appears once."""
    users = (await db.scalars(select(User).where(
        User.is_active.is_(True),
        or_(User.role == UserRole.admin, User.permissions.any(
            (UserPermission.module == "tasks") & UserPermission.can_read.is_(True))),
    ).order_by(User.id))).all()
    groups = [(user.short_name or user.full_name, user.id) for user in users
              if await is_working_day(db, day, user.region)]
    groups.append(("Sin responsable", None))
    lines = [f"\u2600\ufe0f Plan del equipo para hoy · {day:%d/%m/%Y}"]
    any_tasks = False
    for name, owner_id in groups:
        group_lines = []
        for heading, condition in _morning_sections(day):
            tasks = (await db.scalars(select(Task).where(
                Task.assigned_to == owner_id if owner_id is not None else Task.assigned_to.is_(None),
                Task.retired_at.is_(None), Task.status != TaskStatus.completed,
                Task.is_recurring.is_(False), condition,
            ).order_by(_morning_priority_sort(), Task.due_date.asc().nulls_last(), Task.id).limit(9))).all()
            if tasks:
                group_lines.append(f"**{heading}**")
                group_lines.extend(_morning_task_line(task, day, mark_unassigned=False) for task in tasks[:8])
                if len(tasks) > 8:
                    group_lines.append("Hay más en la vista Hoy de la app.")
        if group_lines:
            any_tasks = True
            lines.extend((f"\n**{name}**", *group_lines))
    if not any_tasks:
        lines.append("\nNo hay tareas pendientes visibles en Hoy para esta fecha.")
    return "\n".join(lines)


async def generate_morning_plan(db: AsyncSession, user: User, *, day: date | None = None) -> str:
    """Build the morning task list for a user."""
    name = user.short_name or user.full_name
    today = day or business_today()

    # Match the sections of Hoy. The personal agenda also shows tasks without an
    # assignee, so label those explicitly instead of silently dropping them.
    priority_sort = _morning_priority_sort()
    base = (
        or_(Task.assigned_to == user.id, Task.assigned_to.is_(None)),
        Task.retired_at.is_(None),
        Task.status != TaskStatus.completed,
        Task.is_recurring.is_(False),
    )
    sections = _morning_sections(today)

    lines = [f"\u2600\ufe0f Buenos d\u00edas, {name}", "\U0001f4cb Tu agenda de hoy:"]
    has_tasks = False
    for heading, condition in sections:
        result = await db.execute(
            select(Task).where(*base, condition)
            .order_by(priority_sort, Task.due_date.asc().nulls_last(), Task.id).limit(9)
        )
        tasks = result.scalars().all()
        if not tasks:
            continue
        has_tasks = True
        lines.append(f"\n**{heading}**")
        for task in tasks[:8]:
            lines.append(_morning_task_line(task, today, mark_unassigned=True))
        if len(tasks) > 8:
            lines.append("Hay más en la vista Hoy de la app.")
    if not has_tasks:
        lines.append("\nNo hay tareas pendientes visibles en Hoy para esta fecha.")

    # Meetings today (from Google Calendar sync)
    from datetime import datetime as dt_type
    today_start = dt_type.combine(today, dt_type.min.time())
    today_end = dt_type.combine(today + __import__('datetime').timedelta(days=1), dt_type.min.time())
    meetings_result = await db.execute(
        select(Event).where(
            Event.user_id == user.id,
            Event.event_type == EventType.meeting,
            Event.start_time >= today_start,
            Event.start_time < today_end,
        ).order_by(Event.start_time.asc())
    )
    meetings = meetings_result.scalars().all()
    if meetings:
        lines.append("\n\U0001f4c5 Reuniones hoy:")
        for m in meetings:
            time_str = m.start_time.strftime("%H:%M") if m.start_time else ""
            lines.append(f"  \u2022 {time_str} \u2014 {m.title}")

    lines.append(f"\n\U0001f4aa \u00a1A por ello!")
    return "\n".join(lines)


async def generate_evening_recap(db: AsyncSession, user: User, day: date) -> str:
    """Build the evening recap for a user."""
    name = user.short_name or user.full_name

    day_start, day_end = civil_day_utc_bounds(day)

    # Completed today
    completed_result = await db.execute(
        select(Task).where(
            Task.assigned_to == user.id,
            Task.status == TaskStatus.completed,
            Task.completed_at >= day_start,
            Task.completed_at < day_end,
        )
    )
    completed_tasks = completed_result.scalars().all()

    # Time logged today
    time_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            time_entry_civil_period(day, day + timedelta(days=1)),
            TimeEntry.minutes.isnot(None),
        )
    )
    time_entries = time_result.scalars().all()
    total_minutes = sum(te.minutes for te in time_entries)

    # Pending tasks (not completed today)
    completed_ids = {t.id for t in completed_tasks}
    pending_result = await db.execute(
        select(Task).where(
            Task.assigned_to == user.id,
            Task.retired_at.is_(None),
            Task.status.in_([TaskStatus.pending, *IN_PROGRESS_TASK_STATUSES]),
            Task.is_recurring.is_(False),
        )
    )
    pending_tasks = [t for t in pending_result.scalars().all() if t.id not in completed_ids]

    # Daily update
    daily_result = await db.execute(
        select(DailyUpdate).where(
            DailyUpdate.user_id == user.id,
            DailyUpdate.date == day,
        ).limit(1)
    )
    daily_update = daily_result.scalar_one_or_none()

    # Build message
    lines = [f"\U0001f319 Recap del d\u00eda \u2014 {name}\n"]

    # Completed section
    if completed_tasks:
        lines.append("\u2705 Completado hoy:")
        for t in completed_tasks:
            # Find time logged for this task today
            task_minutes = sum(
                te.minutes for te in time_entries if te.task_id == t.id
            )
            suffix = f" ({_fmt_hours(task_minutes)})" if task_minutes else ""
            lines.append(f"- {t.title}{suffix}")
    else:
        lines.append("\u2705 Completado hoy: ninguna")
    lines.append(
        "Solo se atribuyen a este día las tareas con fecha de finalización registrada."
    )

    lines.append("")

    # Pending section
    if pending_tasks:
        lines.append("\u23f3 Pendiente:")
        for t in pending_tasks:
            lines.append(f"- {t.title} (pendiente)")
    else:
        lines.append("\u23f3 Pendiente: todo al d\u00eda \U0001f389")

    lines.append("")

    # Time total
    lines.append(f"\u23f1\ufe0f Total: {_fmt_hours(total_minutes)} registradas")

    # Daily update
    if daily_update:
        lines.append(f"\n\U0001f4dd Daily update: {daily_update.raw_text[:200]}")
    else:
        lines.append(f"\n\U0001f4dd Daily update: \u26a0\ufe0f No hay un daily guardado para este día")

    return "\n".join(lines)


def _fmt_hours(minutes: int) -> str:
    """Format minutes as Xh or X.Xh."""
    if not minutes:
        return "0h"
    h = minutes / 60
    if h == int(h):
        return f"{int(h)}h"
    return f"{h:.1f}h"


async def send_reminder(message: str, db=None) -> bool:
    """Send a reminder message via Discord webhook."""
    import httpx
    from backend.core.discord_utils import get_webhook_url

    url = await get_webhook_url(db) if db else ""
    if not url.strip():
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "content": message[:2000],
                "username": "Morning Update",
            })
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning("Failed to send daily reminder via Discord: %s", e)
        return False
