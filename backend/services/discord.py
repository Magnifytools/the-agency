from __future__ import annotations

from datetime import datetime, timezone
from collections import defaultdict

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import TimeEntry, Task, User
from backend.config import settings


async def generate_daily_summary(db: AsyncSession, date: datetime) -> str:
    # Remove timezone info for comparison with naive TIMESTAMP columns
    naive = date.replace(tzinfo=None)
    start = naive.replace(hour=0, minute=0, second=0, microsecond=0)
    end = naive.replace(hour=23, minute=59, second=59, microsecond=999999)

    result = await db.execute(
        select(TimeEntry).where(
            and_(
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= start,
                TimeEntry.date <= end,
            )
        )
    )
    entries = result.scalars().all()

    if not entries:
        return f"**Resumen del dia -- {date.strftime('%d/%m/%Y')}**\n\nNo se registraron horas."

    # Group by user -> client -> tasks
    user_data: dict[int, dict] = {}
    for entry in entries:
        uid = entry.user_id
        if uid not in user_data:
            user_data[uid] = {
                "name": entry.user.full_name if entry.user else f"User {uid}",
                "total_minutes": 0,
                "clients": defaultdict(list),
            }
        user_data[uid]["total_minutes"] += entry.minutes
        client_name = entry.task.client.name if entry.task and entry.task.client else "Sin cliente"
        task_title = entry.task.title if entry.task else "Sin tarea"
        user_data[uid]["clients"][client_name].append({
            "task": task_title,
            "minutes": entry.minutes,
        })

    def _fmt(minutes: int) -> str:
        h, m = divmod(minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        if h:
            return f"{h}h"
        return f"{m}m"

    lines = [f"**Resumen del dia -- {date.strftime('%d/%m/%Y')}**\n"]

    total_team_minutes = 0
    for uid, data in user_data.items():
        total_team_minutes += data["total_minutes"]
        lines.append(f"**{data['name']}** ({_fmt(data['total_minutes'])})")
        for client_name, tasks in data["clients"].items():
            # Aggregate tasks with same name
            task_times: dict[str, int] = defaultdict(int)
            for t in tasks:
                task_times[t["task"]] += t["minutes"]
            task_strs = [f"{name} ({_fmt(mins)})" for name, mins in task_times.items()]
            lines.append(f"  * {client_name}: {', '.join(task_strs)}")
        lines.append("")

    lines.append(f"**Total equipo: {_fmt(total_team_minutes)}**")
    return "\n".join(lines)


async def send_to_discord(message: str) -> bool:
    url = settings.DISCORD_WEBHOOK_URL
    if not url:
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={"content": message})
        return resp.status_code in (200, 204)
