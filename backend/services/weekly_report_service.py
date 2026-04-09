"""Weekly report service — generates the Saturday team report for Discord DM."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    User, TimeEntry, Task, Client, Project, TaskStatus,
)
from backend.startup.background_tasks import _is_qa_user

logger = logging.getLogger(__name__)
MADRID_TZ = ZoneInfo("Europe/Madrid")


def _fmt_h(minutes: float) -> str:
    h = minutes / 60.0
    return f"{int(h)}h" if h == int(h) else f"{h:.1f}h"


async def generate_weekly_report(db: AsyncSession) -> str:
    """Generate the full weekly report text. Returns Discord-formatted string."""
    now = datetime.now(MADRID_TZ)
    today = now.date()
    ws = today - timedelta(days=5)  # Monday (Saturday - 5)
    we_fri = ws + timedelta(days=4)
    we_sun = ws + timedelta(days=6)
    start_dt = datetime.combine(ws, datetime.min.time())
    end_dt = datetime.combine(we_sun + timedelta(days=1), datetime.min.time())

    # Users
    users_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    )
    users = [u for u in users_result.scalars().all() if not _is_qa_user(u)]
    user_map = {u.id: u for u in users}

    # Time entries
    entries_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start_dt,
            TimeEntry.date < end_dt,
        )
    )
    entries = entries_result.scalars().all()

    # Tasks
    completed_result = await db.execute(
        select(Task).options(selectinload(Task.client))
        .where(Task.status == TaskStatus.completed, Task.updated_at >= start_dt, Task.updated_at < end_dt)
        .order_by(Task.client_id, Task.title)
    )
    completed_tasks = completed_result.scalars().all()

    in_progress_result = await db.execute(
        select(Task).options(selectinload(Task.client), selectinload(Task.assigned_user))
        .where(Task.status == TaskStatus.in_progress).order_by(Task.client_id, Task.title)
    )
    in_progress_tasks = in_progress_result.scalars().all()

    pending_result = await db.execute(
        select(Task).options(selectinload(Task.client), selectinload(Task.assigned_user))
        .where(Task.status == TaskStatus.pending).order_by(Task.due_date.asc().nulls_last(), Task.title).limit(15)
    )
    pending_tasks = pending_result.scalars().all()

    overdue_result = await db.execute(
        select(Task).options(selectinload(Task.client), selectinload(Task.assigned_user))
        .where(Task.status.notin_([TaskStatus.completed]), Task.due_date < start_dt, Task.due_date.isnot(None))
        .order_by(Task.due_date.asc()).limit(15)
    )
    overdue_tasks = overdue_result.scalars().all()

    # Aggregate time
    task_ids = {e.task_id for e in entries if e.task_id}
    tasks_map: dict[int, dict] = {}
    if task_ids:
        task_result = await db.execute(
            select(Task, Client.name.label("client_name"), Project.monthly_fee)
            .outerjoin(Client, Task.client_id == Client.id)
            .outerjoin(Project, Task.project_id == Project.id)
            .where(Task.id.in_(task_ids))
        )
        for row in task_result.all():
            tasks_map[row[0].id] = {"client_name": row[1] or "Sin cliente", "monthly_fee": row[2] or 0}

    user_hours: dict[int, float] = {}
    client_hours: dict[str, float] = {}
    client_cost: dict[str, float] = {}

    for entry in entries:
        mins = entry.minutes or 0
        uid = entry.user_id
        if uid not in user_map:
            continue
        user_hours[uid] = user_hours.get(uid, 0) + mins
        client_name = tasks_map.get(entry.task_id, {}).get("client_name", "Sin cliente") if entry.task_id else "Sin cliente"
        client_hours[client_name] = client_hours.get(client_name, 0) + mins
        rate = float(user_map[uid].hourly_rate) if user_map[uid].hourly_rate else float(settings.DEFAULT_HOURLY_RATE)
        client_cost[client_name] = client_cost.get(client_name, 0) + (mins / 60.0) * rate

    # Build report
    total_mins = sum(user_hours.values())
    total_capacity_mins = sum((u.weekly_hours or 40) * 60 for u in users)
    lines: list[str] = []

    lines.append(f"\U0001f4ca **Repaso Semanal \u2014 {ws.strftime('%d/%m')} al {we_fri.strftime('%d/%m/%Y')}**")
    lines.append("")

    if total_capacity_mins:
        pct = total_mins / total_capacity_mins * 100
        lines.append(f"\u23f1\ufe0f **Tiempo total:** {_fmt_h(total_mins)} / {_fmt_h(total_capacity_mins)} ({pct:.0f}% capacidad)")
    else:
        lines.append(f"\u23f1\ufe0f **Tiempo total:** {_fmt_h(total_mins)}")
    lines.append(f"\u2705 **Tareas completadas:** {len(completed_tasks)}")
    lines.append(f"\U0001f504 **En progreso:** {len(in_progress_tasks)}")
    lines.append(f"\U0001f4cb **Pendientes:** {len(pending_tasks)}")
    if overdue_tasks:
        lines.append(f"\U0001f534 **Vencidas:** {len(overdue_tasks)}")
    lines.append("")

    # Per person
    lines.append("\U0001f465 **Tiempo por persona:**")
    for u in users:
        mins = user_hours.get(u.id, 0)
        cap = (u.weekly_hours or 40) * 60
        name = u.short_name or u.full_name
        pct = mins / cap * 100 if cap else 0
        bar = "\U0001f7e9" if pct >= 80 else ("\U0001f7e8" if pct >= 50 else "\U0001f7e5")
        lines.append(f"  {bar} {name}: {_fmt_h(mins)} / {_fmt_h(cap)} ({pct:.0f}%)")
    lines.append("")

    # Completed by client
    if completed_tasks:
        lines.append("\u2705 **Completado esta semana:**")
        by_client: dict[str, list[str]] = {}
        for t in completed_tasks:
            cn = t.client.name if t.client else "Sin cliente"
            assignee = ""
            if t.assigned_to and t.assigned_to in user_map:
                u = user_map[t.assigned_to]
                assignee = f" ({u.short_name or u.full_name})"
            by_client.setdefault(cn, []).append(f"{t.title}{assignee}")
        for cn, items in sorted(by_client.items()):
            lines.append(f"  **{cn}:**")
            for item in items:
                lines.append(f"    \u2022 {item}")
        lines.append("")

    # In progress
    if in_progress_tasks:
        lines.append("\U0001f504 **En progreso:**")
        for t in in_progress_tasks:
            cn = t.client.name if t.client else "Sin cliente"
            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}" if t.assigned_user else ""
            due = ""
            if t.due_date:
                d = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
                due = f" (vence {d.strftime('%d/%m')})"
            lines.append(f"  \u2022 [{cn}] {t.title}{assignee}{due}")
        lines.append("")

    # Client hours
    if client_hours:
        lines.append("\U0001f3e2 **Tiempo por cliente:**")
        for name, mins in sorted(client_hours.items(), key=lambda x: x[1], reverse=True):
            cost = client_cost.get(name, 0)
            pct = (mins / total_mins * 100) if total_mins else 0
            alert = " \u26a0\ufe0f" if pct > 40 else ""
            lines.append(f"  \u2022 {name}: {_fmt_h(mins)} ({pct:.0f}%) \u2014 {cost:.0f}\u20ac{alert}")

        active_clients_result = await db.execute(select(Client.name).where(Client.status == "active"))
        inactive = {r[0] for r in active_clients_result.all()} - set(client_hours.keys())
        if inactive:
            lines.append(f"  \U0001f4a4 Sin actividad: {', '.join(sorted(inactive))}")
        lines.append("")

    # Overdue
    if overdue_tasks:
        lines.append(f"\U0001f534 **Tareas vencidas ({len(overdue_tasks)}):**")
        for t in overdue_tasks[:10]:
            cn = t.client.name if t.client else "Sin cliente"
            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}" if t.assigned_user else ""
            due = t.due_date.strftime("%d/%m") if t.due_date else "?"
            lines.append(f"  \u2022 [{cn}] {t.title}{assignee} (venc\u00eda {due})")
        if len(overdue_tasks) > 10:
            lines.append(f"  ... y {len(overdue_tasks) - 10} m\u00e1s")
        lines.append("")

    # Upcoming
    upcoming = [t for t in pending_tasks if t.due_date]
    if upcoming:
        lines.append("\U0001f4cb **Pr\u00f3ximas pendientes:**")
        for t in upcoming[:8]:
            cn = t.client.name if t.client else "Sin cliente"
            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}" if t.assigned_user else ""
            d = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
            lines.append(f"  \u2022 [{cn}] {t.title}{assignee} (vence {d.strftime('%d/%m')})")
        lines.append("")

    lines.append("\U0001f4aa \u00a1Buen finde!")
    return "\n".join(lines)
