"""Daily reminders service — morning plan & evening recap via Discord."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select, and_, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Task, TaskStatus, TaskPriority, TimeEntry, DailyUpdate,
    CompanyHoliday, User,
)
import re

from backend.services.discord import send_to_discord

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


async def generate_morning_plan(db: AsyncSession, user: User) -> str:
    """Build the morning task list for a user."""
    name = user.short_name or user.full_name

    # Fetch active tasks ordered by priority then due_date
    priority_sort = case(
        {
            TaskPriority.urgent: 0,
            TaskPriority.high: 1,
            TaskPriority.medium: 2,
            TaskPriority.low: 3,
        },
        value=Task.priority,
        else_=4,
    )
    stmt = (
        select(Task)
        .where(
            Task.assigned_to == user.id,
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
        )
        .order_by(priority_sort, Task.due_date.asc().nulls_last())
    )
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    if not tasks:
        return f"\u2600\ufe0f Buenos d\u00edas, {name}\n\n\u2705 No tienes tareas pendientes. \u00a1Buen d\u00eda!"

    today = date.today()
    lines = [
        f"\u2600\ufe0f Buenos d\u00edas, {name}",
        f"\U0001f4cb Tus tareas para hoy:\n",
    ]

    for t in tasks:
        order, emoji = _PRIORITY_ORDER.get(t.priority, (4, "\u26aa"))
        client_name = t.client.name if t.client else None

        title = _MONEY_RE.sub("", t.title).strip()
        parts = [emoji]
        if t.priority == TaskPriority.urgent:
            parts.append("[URGENTE]")
        parts.append(title)
        if client_name:
            parts.append(f"\u2014 {client_name}")

        # Due date annotation
        if t.due_date:
            due_day = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
            if due_day < today:
                parts.append("(vencida)")
            elif due_day == today:
                parts.append("(vence hoy)")
            else:
                parts.append(f"(vence {due_day.strftime('%d/%m')})")

        lines.append(" ".join(parts))

    lines.append(f"\n\U0001f4aa \u00a1A por ello!")
    return "\n".join(lines)


async def generate_evening_recap(db: AsyncSession, user: User, day: date) -> str:
    """Build the evening recap for a user."""
    name = user.short_name or user.full_name

    day_start = f"{day.isoformat()} 00:00:00"
    day_end = f"{day.isoformat()} 23:59:59"

    # Completed today
    completed_result = await db.execute(
        select(Task).where(
            Task.assigned_to == user.id,
            Task.status == TaskStatus.completed,
            Task.updated_at >= day_start,
            Task.updated_at <= day_end,
        )
    )
    completed_tasks = completed_result.scalars().all()

    # Time logged today
    time_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.user_id == user.id,
            TimeEntry.date >= day_start,
            TimeEntry.date <= day_end,
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
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
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

    lines.append("")

    # Pending section
    if pending_tasks:
        lines.append("\u23f3 Pendiente:")
        for t in pending_tasks:
            lines.append(f"- {t.title} (no tocada)")
    else:
        lines.append("\u23f3 Pendiente: todo al d\u00eda \U0001f389")

    lines.append("")

    # Time total
    lines.append(f"\u23f1\ufe0f Total: {_fmt_hours(total_minutes)} registradas")

    # Daily update
    if daily_update:
        lines.append(f"\n\U0001f4dd Daily update: {daily_update.raw_text[:200]}")
    else:
        lines.append(f"\n\U0001f4dd Daily update: \u26a0\ufe0f No has enviado tu daily")

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
    """Send a reminder message via Discord.

    Reads the webhook URL from discord_settings (DB) first, falling back
    to the DISCORD_WEBHOOK_URL env var.  Previous code only checked the
    env var which was never set in production.
    """
    import httpx
    from backend.config import settings

    url: str = ""
    # Try DB-stored webhook first
    if db is not None:
        try:
            from sqlalchemy import select
            from backend.db.models import DiscordSettings
            from backend.core.security import decrypt_vault_secret

            result = await db.execute(select(DiscordSettings).limit(1))
            ds = result.scalar_one_or_none()
            if ds and ds.webhook_url:
                raw = ds.webhook_url
                if raw.startswith("v1:"):
                    url = decrypt_vault_secret(raw)
                else:
                    url = raw
        except Exception as e:
            logger.warning("Failed to read Discord settings from DB: %s", e)

    # Fallback to env var
    if not url:
        url = settings.DISCORD_WEBHOOK_URL or ""

    if not url.strip():
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "content": message[:2000],
                "username": "☀️ Morning Update",
            })
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning("Failed to send daily reminder via Discord: %s", e)
        return False
