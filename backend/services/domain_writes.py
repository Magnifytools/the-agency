"""Commit-free domain writers used by routes and future command adapters."""
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.core.modules import is_enabled

from backend.db.models import (
    Client,
    ClientContact,
    Project,
    Task,
    TaskStatus,
    TimeEntry,
    User,
)
from backend.services.change_journal import capture_manual_time
from backend.services.project_lifecycle import (
    ensure_project_allows_task_state,
    task_project_state,
)
from backend.services.project_owner import validate_project_owner
from backend.services.recurrence import validate_recurrence_rule
from backend.services.task_lifecycle import stamp_task_status, validate_task_waiting
from backend.services.task_review import validate_project_review, validate_task_review
from backend.services.task_scope import validate_client_exists, validate_task_scope
from backend.services.temporal import business_today, utc_now_naive
from backend.services.time_entry_dates import manual_time_entry_date
from backend.services.write_access import require_current_write

UPDATABLE_TASK_FIELDS = {
    "title", "description", "status", "priority", "estimated_minutes",
    "actual_minutes", "start_date", "due_date", "client_id", "category_id",
    "assigned_to", "project_id", "phase_id", "depends_on", "scheduled_date",
    "waiting_for", "follow_up_date", "is_recurring", "recurrence_pattern",
    "recurrence_day", "recurrence_end_date", "unit_cost",
    "link_url", "recurrence_anchor_date", "recurrence_paused",
}

RETIRED_TASK_EDITABLE_FIELDS = {"title", "description", "link_url"}


async def create_client(db: AsyncSession, data: dict) -> Client:
    """Create a client inside the caller's transaction."""
    client = Client(**data)
    db.add(client)
    await db.flush()
    return client


async def create_contact(db: AsyncSession, client_id: int, data: dict) -> ClientContact:
    """Create a contact while serializing the per-client primary invariant."""
    client = (await db.execute(
        select(Client).where(Client.id == client_id).options(noload("*")).with_for_update()
    )).scalar_one_or_none()
    if client is None:
        raise HTTPException(404, "Client not found")
    if data.get("is_primary"):
        primaries = (await db.execute(
            select(ClientContact).where(
                ClientContact.client_id == client_id,
                ClientContact.is_primary.is_(True),
            ).order_by(ClientContact.id).with_for_update()
        )).scalars().all()
        for contact in primaries:
            contact.is_primary = False
    contact = ClientContact(client_id=client_id, **data)
    db.add(contact)
    await db.flush()
    return contact


def _prepare_recurrence(data: dict, *, existing: Task | None = None) -> None:
    preserves_legacy_biweekly = bool(
        existing and existing.is_recurring and existing.recurrence_pattern == "biweekly"
        and existing.recurrence_anchor_date is None
    )
    is_recurring = data.get("is_recurring", existing.is_recurring if existing else False)
    pattern = data.get("recurrence_pattern", existing.recurrence_pattern if existing else None)
    day = data.get("recurrence_day", existing.recurrence_day if existing else None)
    anchor = data.get("recurrence_anchor_date", existing.recurrence_anchor_date if existing else None)
    end = data.get("recurrence_end_date", existing.recurrence_end_date if existing else None)
    if (
        existing and existing.is_recurring and existing.recurrence_pattern == "biweekly"
        and existing.recurrence_anchor_date is not None
        and "recurrence_anchor_date" in data and data["recurrence_anchor_date"] is None
    ):
        raise HTTPException(422, "Indica la fecha de inicio de la recurrencia bisemanal")
    if is_recurring and pattern == "biweekly" and anchor is None and not preserves_legacy_biweekly:
        anchor = business_today()
        data["recurrence_anchor_date"] = anchor
    try:
        validate_recurrence_rule(
            is_recurring=is_recurring, pattern=pattern, day=day,
            anchor_date=anchor, end_date=end,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if "recurrence_paused" in data:
        paused = data.pop("recurrence_paused")
        if paused is None:
            raise HTTPException(422, "Indica si quieres pausar o reanudar la recurrencia")
        data["recurrence_paused_at"] = utc_now_naive() if paused else None


async def create_project(db: AsyncSession, data: dict) -> Project:
    await validate_client_exists(db, data.get("client_id"))
    await validate_project_owner(db, data.get("owner_id"))
    await validate_project_review(db, data)
    project = Project(**data)
    db.add(project)
    await db.flush()
    return project


def _can_write_time(actor: User | None) -> bool:
    return actor is not None and (actor.role.value == "admin" or any(
        p.module == "timesheet" and p.can_write for p in (actor.permissions or [])
    ))


async def create_task(
    db: AsyncSession, data: dict, *, actor: User | None, created_by: int | None = None,
    manual_entry_date=None,
) -> Task:
    data = dict(data)
    _prepare_recurrence(data)
    await validate_task_scope(db, data)
    actual = data.get("actual_minutes")
    await require_current_write(db, actor, {"tasks", "timesheet"} if actual else {"tasks"})
    await validate_task_waiting(db, data)
    await validate_task_review(db, data, actor)
    await ensure_project_allows_task_state(
        db, state=task_project_state(overrides=data), creating=True,
    )
    if actual and not _can_write_time(actor):
        raise HTTPException(403, "Crear horas reales requiere permiso de escritura en timesheet")
    if actual:
        capture_manual_time(db.sync_session)
    task = Task(**data, created_by=actor.id if actor else created_by)
    stamp_task_status(task)
    db.add(task)
    await db.flush()
    if actual:
        db.add(TimeEntry(task_id=task.id, user_id=actor.id, minutes=actual,
                         date=manual_entry_date or manual_time_entry_date(), notes="[manual]"))
        await db.flush()
    return task


async def lock_task(db: AsyncSession, task_id: int) -> Task:
    task = (await db.execute(select(Task).where(Task.id == task_id).options(noload("*")).with_for_update()
             .execution_options(populate_existing=True))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


async def lock_task_dependency_change(
    db: AsyncSession, task_id: int, dependency_id: int | None,
) -> Task:
    """Lock a task and its proposed dependency in deterministic id order."""
    ids = sorted({value for value in (task_id, dependency_id) if value is not None})
    rows = (await db.execute(
        select(Task).where(Task.id.in_(ids)).order_by(Task.id)
        .options(noload("*")).with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().all()
    by_id = {row.id: row for row in rows}
    task = by_id.get(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


async def lock_task_patch(db: AsyncSession, task_id: int, data: dict) -> Task:
    """Lock every Task row whose lifecycle can affect this patch, in id order."""
    dependency_id = data.get("depends_on") if "depends_on" in data else None
    verify_current_dependency = False
    requested_status = data.get("status")
    requested_status_value = getattr(requested_status, "value", requested_status)
    if "depends_on" not in data and requested_status_value not in (None, TaskStatus.completed.value):
        dependency_id = await db.scalar(select(Task.depends_on).where(Task.id == task_id))
        verify_current_dependency = True
    if dependency_id is None:
        return await lock_task(db, task_id)
    task = await lock_task_dependency_change(db, task_id, dependency_id)
    if verify_current_dependency and task.depends_on != dependency_id:
        raise HTTPException(409, "La dependencia cambió; vuelve a intentarlo")
    return task


async def update_task(
    db: AsyncSession, task: Task, data: dict, *, actor: User | None, manual_entry_date=None,
    allow_assignee_schedule: bool = False,
) -> Task:
    """Apply a validated task patch; caller owns transaction and response effects."""
    # The writer is also called by automation/command adapters. Re-lock and
    # refresh here so no stale ORM instance can bypass retirement invariants.
    data = dict(data)
    task = await lock_task_patch(db, task.id, data)
    previous_project_state = task_project_state(task)
    manual_changed = "actual_minutes" in data and data["actual_minutes"] != task.actual_minutes
    # My Week deliberately lets an assignee schedule their own work without
    # granting general task editing. This exception is scalar and exact, after
    # the task is locked; it cannot authorize status, scope, or time changes.
    owns_schedule = bool(
        allow_assignee_schedule and actor is not None
        and task.assigned_to == actor.id and set(data) == {"scheduled_date"}
    )
    if owns_schedule and not is_enabled("tasks"):
        raise HTTPException(403, "Módulo no disponible: tasks")
    required = set() if owns_schedule else {"tasks"}
    if manual_changed:
        required.add("timesheet")
    await require_current_write(db, actor, required)
    unsupported = sorted(set(data) - UPDATABLE_TASK_FIELDS)
    if unsupported:
        raise HTTPException(422, f"Campos de tarea no editables: {', '.join(unsupported)}")
    changed_fields = {
        field for field, value in data.items()
        if field != "recurrence_paused" and getattr(task, field, None) != value
    }
    if "recurrence_paused" in data:
        requested_paused = data["recurrence_paused"]
        if requested_paused is None or requested_paused != (task.recurrence_paused_at is not None):
            changed_fields.add("recurrence_paused")
    if task.retired_at is not None and changed_fields - RETIRED_TASK_EDITABLE_FIELDS:
        raise HTTPException(409, "Restaura la tarea antes de cambiar su trabajo operativo")
    await validate_task_waiting(db, data, existing=task)
    _prepare_recurrence(data, existing=task)
    old_status = task.status
    if manual_changed and not _can_write_time(actor):
        raise HTTPException(403, "Editar horas reales requiere permiso de escritura en timesheet")
    if manual_changed:
        capture_manual_time(db.sync_session)
    new_actual = data.get("actual_minutes")
    await validate_task_scope(db, data, existing=task)
    await ensure_project_allows_task_state(
        db,
        state=task_project_state(task, data),
        previous_state=previous_project_state,
    )
    await validate_task_review(db, data, actor, existing=task)
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
