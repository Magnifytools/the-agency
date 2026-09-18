"""Commit-free domain writers used by routes and future command adapters."""
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, Task, TimeEntry, User
from backend.services.change_journal import capture_manual_time
from backend.services.project_owner import validate_project_owner
from backend.services.task_lifecycle import stamp_task_status
from backend.services.task_scope import validate_client_exists, validate_task_scope
from backend.services.time_entry_dates import manual_time_entry_date

UPDATABLE_TASK_FIELDS = {
    "title", "description", "status", "priority", "estimated_minutes",
    "actual_minutes", "start_date", "due_date", "client_id", "category_id",
    "assigned_to", "project_id", "phase_id", "depends_on", "scheduled_date",
    "waiting_for", "follow_up_date", "is_recurring", "recurrence_pattern",
    "recurrence_day", "recurrence_end_date", "recurring_parent_id", "unit_cost",
    "link_url",
}


async def create_project(db: AsyncSession, data: dict) -> Project:
    await validate_client_exists(db, data.get("client_id"))
    await validate_project_owner(db, data.get("owner_id"))
    project = Project(**data)
    db.add(project)
    await db.flush()
    return project


def _can_write_time(actor: User | None) -> bool:
    return actor is not None and (actor.role.value == "admin" or any(
        p.module == "timesheet" and p.can_write for p in (actor.permissions or [])
    ))


async def create_task(
    db: AsyncSession, data: dict, *, actor: User | None, manual_entry_date=None,
) -> Task:
    data = dict(data)
    await validate_task_scope(db, data)
    actual = data.get("actual_minutes")
    if actual and not _can_write_time(actor):
        raise HTTPException(403, "Crear horas reales requiere permiso de escritura en timesheet")
    if actual:
        capture_manual_time(db.sync_session)
    task = Task(**data, created_by=actor.id if actor else None)
    stamp_task_status(task)
    db.add(task)
    await db.flush()
    if actual:
        db.add(TimeEntry(task_id=task.id, user_id=actor.id, minutes=actual,
                         date=manual_entry_date or manual_time_entry_date(), notes="[manual]"))
        await db.flush()
    return task


async def lock_task(db: AsyncSession, task_id: int) -> Task:
    task = (await db.execute(select(Task).where(Task.id == task_id).with_for_update()
             .execution_options(populate_existing=True))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


async def update_task(
    db: AsyncSession, task: Task, data: dict, *, actor: User | None, manual_entry_date=None,
) -> Task:
    """Apply a validated task patch; caller owns transaction and response effects."""
    data = dict(data)
    unsupported = sorted(set(data) - UPDATABLE_TASK_FIELDS)
    if unsupported:
        raise HTTPException(422, f"Campos de tarea no editables: {', '.join(unsupported)}")
    old_status = task.status
    manual_changed = "actual_minutes" in data and data["actual_minutes"] != task.actual_minutes
    if manual_changed and not _can_write_time(actor):
        raise HTTPException(403, "Editar horas reales requiere permiso de escritura en timesheet")
    if manual_changed:
        capture_manual_time(db.sync_session)
    new_actual = data.get("actual_minutes")
    await validate_task_scope(db, data, existing=task)
    for field, value in data.items():
        setattr(task, field, value)
    if "status" in data:
        stamp_task_status(task, old_status)
    if manual_changed:
        fixed_sum = (await db.execute(select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.task_id == task.id, TimeEntry.minutes.isnot(None),
            or_(TimeEntry.notes.is_(None), TimeEntry.notes != "[manual]", TimeEntry.user_id != actor.id),
        ))).scalar() or 0
        target = fixed_sum if new_actual is None else new_actual
        if target < fixed_sum:
            raise HTTPException(422, f"Las horas reales no pueden ser menores que los {fixed_sum} minutos ya registrados")
        desired = target - fixed_sum
        entries = list((await db.execute(select(TimeEntry).where(
            TimeEntry.task_id == task.id, TimeEntry.user_id == actor.id, TimeEntry.notes == "[manual]",
        ).order_by(TimeEntry.date.desc(), TimeEntry.id.desc()))).scalars().all())
        current = sum(entry.minutes or 0 for entry in entries)
        task.actual_minutes = target or None
        if desired > current:
            increase = desired - current
            if entries:
                entries[0].minutes = (entries[0].minutes or 0) + increase
            else:
                db.add(TimeEntry(task_id=task.id, user_id=actor.id, minutes=increase,
                                 date=manual_entry_date or manual_time_entry_date(), notes="[manual]"))
        elif desired < current:
            reduction = current - desired
            for entry in entries:
                amount = entry.minutes or 0
                if reduction >= amount:
                    reduction -= amount
                    await db.delete(entry)
                else:
                    entry.minutes = amount - reduction
                    break
    await db.flush()
    return task
