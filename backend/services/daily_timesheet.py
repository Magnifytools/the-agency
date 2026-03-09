"""Auto-generate TimeEntry records from a parsed daily update."""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Task, TaskStatus, TimeEntry

logger = logging.getLogger(__name__)


async def create_time_entries_from_daily(
    db: AsyncSession,
    user_id: int,
    daily_date: date,
    parsed_data: dict,
) -> int:
    """Match parsed daily tasks to real Task records and create TimeEntry rows.

    Returns the number of time entries created.
    """
    created = 0
    daily_dt = datetime.combine(daily_date, datetime.min.time())

    projects = parsed_data.get("projects", [])
    general = parsed_data.get("general", [])

    # Process project-scoped tasks
    for proj in projects:
        client_name = proj.get("client", "") or proj.get("name", "")
        tasks = proj.get("tasks", [])

        # Try to find the client by name
        client_id = await _find_client_id(db, client_name) if client_name else None

        for task_info in tasks:
            desc = task_info.get("description", "")
            if not desc:
                continue

            matched_task = await _find_task(db, desc, client_id=client_id)
            if not matched_task:
                continue

            # Dedup: skip if entry already exists for same user + task + date
            exists = await db.execute(
                select(TimeEntry.id).where(
                    TimeEntry.user_id == user_id,
                    TimeEntry.task_id == matched_task.id,
                    func.date(TimeEntry.date) == daily_date,
                ).limit(1)
            )
            if exists.scalar():
                continue

            minutes = matched_task.estimated_minutes or 30  # fallback 30min
            entry = TimeEntry(
                user_id=user_id,
                task_id=matched_task.id,
                date=daily_dt,
                minutes=minutes,
                notes=f"[Daily] {desc}",
            )
            db.add(entry)
            created += 1

    # Process general (no client) tasks
    for task_info in general:
        desc = task_info.get("description", "")
        if not desc:
            continue

        matched_task = await _find_task(db, desc, client_id=None)
        if not matched_task:
            continue

        exists = await db.execute(
            select(TimeEntry.id).where(
                TimeEntry.user_id == user_id,
                TimeEntry.task_id == matched_task.id,
                func.date(TimeEntry.date) == daily_date,
            ).limit(1)
        )
        if exists.scalar():
            continue

        minutes = matched_task.estimated_minutes or 30
        entry = TimeEntry(
            user_id=user_id,
            task_id=matched_task.id,
            date=daily_dt,
            minutes=minutes,
            notes=f"[Daily] {desc}",
        )
        db.add(entry)
        created += 1

    if created:
        await db.flush()

    return created


async def _find_client_id(db: AsyncSession, name: str) -> int | None:
    """Find a client by name (case-insensitive partial match)."""
    result = await db.execute(
        select(Client.id).where(Client.name.ilike(f"%{name}%")).limit(1)
    )
    return result.scalar()


async def _find_task(
    db: AsyncSession,
    description: str,
    client_id: int | None = None,
) -> Task | None:
    """Find a Task by fuzzy title match.

    Strategy:
    1. Exact title match (case-insensitive)
    2. Partial match using keywords from the description
    Only considers non-completed tasks first, then completed.
    """
    desc_clean = description.strip()
    if not desc_clean:
        return None

    # 1) Exact match (ilike)
    q = select(Task).where(
        Task.title.ilike(desc_clean),
        Task.status != TaskStatus.completed,
    )
    if client_id:
        q = q.where(Task.client_id == client_id)
    result = await db.execute(q.limit(1))
    task = result.scalars().first()
    if task:
        return task

    # 2) Partial match — title contains the description
    q = select(Task).where(
        Task.title.ilike(f"%{desc_clean}%"),
        Task.status != TaskStatus.completed,
    )
    if client_id:
        q = q.where(Task.client_id == client_id)
    result = await db.execute(q.limit(1))
    task = result.scalars().first()
    if task:
        return task

    # 3) Keyword match — use first 3 significant words
    words = [w for w in desc_clean.split() if len(w) > 3][:3]
    if words:
        q = select(Task).where(Task.status != TaskStatus.completed)
        if client_id:
            q = q.where(Task.client_id == client_id)
        for word in words:
            q = q.where(Task.title.ilike(f"%{word}%"))
        result = await db.execute(q.limit(1))
        task = result.scalars().first()
        if task:
            return task

    return None
