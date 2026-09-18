"""Transactional time-entry writes shared by HTTP and future command adapters."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Task, TimeEntry
from backend.services.time_entry_dates import manual_time_entry_date


async def lock_tasks(db: AsyncSession, task_ids: set[int]) -> dict[int, Task]:
    if not task_ids:
        return {}
    rows = (await db.execute(
        select(Task).where(Task.id.in_(sorted(task_ids))).order_by(Task.id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalars().all()
    return {task.id: task for task in rows}


async def sync_task_actual_minutes(db: AsyncSession, task_id: int, *, task: Task | None = None) -> None:
    if task is None:
        task = (await lock_tasks(db, {task_id})).get(task_id)
    if task is None:
        return
    timer_mins = (await db.execute(select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
        TimeEntry.task_id == task_id, TimeEntry.minutes.isnot(None),
        or_(TimeEntry.notes != "[manual]", TimeEntry.notes.is_(None)),
    ))).scalar() or 0
    manual_mins = (await db.execute(select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
        TimeEntry.task_id == task_id, TimeEntry.notes == "[manual]",
    ))).scalar() or 0
    task.actual_minutes = int(timer_mins + manual_mins) or None


async def create_manual_time_entry(
    db: AsyncSession, *, user_id: int, minutes: int, task_id: int | None = None,
    notes: str | None = None, entry_date: datetime | None = None,
) -> TimeEntry:
    """Add explicit time and update its task cache, without committing."""
    if minutes <= 0:
        raise HTTPException(422, "Los minutos deben ser mayores a 0")
    locked: dict[int, Task] = {}
    if task_id is not None:
        locked = await lock_tasks(db, {task_id})
        if task_id not in locked:
            raise HTTPException(404, "Task not found")
    if entry_date is not None and entry_date.tzinfo is not None:
        entry_date = entry_date.astimezone(timezone.utc).replace(tzinfo=None)
    entry = TimeEntry(user_id=user_id, minutes=minutes, task_id=task_id, notes=notes,
                      date=entry_date or manual_time_entry_date())
    db.add(entry)
    await db.flush()
    if task_id is not None:
        await sync_task_actual_minutes(db, task_id, task=locked[task_id])
    return entry
