"""Atomic carryover decisions and durable task retirement."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.db.models import Task, TaskStatus, TimeEntry, User
from backend.services.domain_writes import update_task
from backend.services.temporal import business_today, utc_now_naive


def _datetime_epoch(value: datetime) -> Decimal:
    """Exact epoch microseconds; naive values follow the API's naive-UTC contract."""
    instant = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    delta = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
    micros = ((delta.days * 86400 + delta.seconds) * 1_000_000) + delta.microseconds
    return Decimal(micros) / Decimal(1_000_000)


async def lock_task_for_cas(
    db: AsyncSession, task_id: int, expected_updated_at: datetime, *,
    lock_dependency: bool = False,
) -> Task:
    dependency_id = None
    if lock_dependency:
        dependency_id = await db.scalar(select(Task.depends_on).where(Task.id == task_id))
    ids = sorted({value for value in (task_id, dependency_id) if value is not None})
    rows = (await db.execute(
        select(Task, func.extract("epoch", Task.updated_at).label("updated_epoch"))
        .where(Task.id.in_(ids))
        .options(noload("*"))
        .order_by(Task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).all()
    row = next((item for item in rows if item[0].id == task_id), None)
    if row is None:
        raise HTTPException(404, "Task not found")
    task, updated_epoch = row
    if lock_dependency and task.depends_on != dependency_id:
        raise HTTPException(409, "La dependencia cambió; actualiza la vista y vuelve a intentarlo")
    if Decimal(updated_epoch) != _datetime_epoch(expected_updated_at):
        raise HTTPException(409, "La tarea cambió; actualiza la vista y vuelve a intentarlo")
    return task


def _is_carryover(task: Task) -> bool:
    if task.retired_at is not None or task.status == TaskStatus.completed:
        return False
    today = business_today()
    due_day = task.due_date.date() if task.due_date is not None else None
    return bool(
        (due_day is not None and due_day < today)
        or (
            task.scheduled_date is not None
            and task.scheduled_date < today
            and due_day != today
        )
    )


async def apply_carryover_decision(
    db: AsyncSession, task: Task, data: dict, *, actor: User,
) -> Task:
    if not _is_carryover(task):
        raise HTTPException(409, "La tarea ya no está en el arrastre; actualiza la vista")
    action = data["action"]
    if action == "reschedule":
        scheduled_date = data.get("scheduled_date")
        if scheduled_date is None:
            raise HTTPException(422, "Indica la nueva fecha planificada")
        changes = {"scheduled_date": scheduled_date}
    elif action == "wait":
        waiting_for = (data.get("waiting_for") or "").strip()
        follow_up_date = data.get("follow_up_date")
        if not waiting_for:
            raise HTTPException(422, "Indica qué está esperando la tarea")
        if follow_up_date is None or follow_up_date < business_today():
            raise HTTPException(422, "La fecha de revisión debe ser hoy o posterior")
        changes = {
            "status": TaskStatus.waiting,
            "waiting_for": waiting_for,
            "follow_up_date": follow_up_date,
            "scheduled_date": None,
        }
    elif action == "complete":
        changes = {"status": TaskStatus.completed}
    elif action == "retire":
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise HTTPException(422, "Indica el motivo de retirada")
        await ensure_can_retire(db, task)
        task.retired_at = utc_now_naive()
        task.retired_reason = reason
        await db.flush()
        return task
    else:  # schema prevents this; keep the domain writer total.
        raise HTTPException(422, "Decisión de arrastre no válida")
    return await update_task(db, task, changes, actor=actor)


async def restore_task(db: AsyncSession, task: Task, *, actor: User) -> Task:
    await ensure_can_restore(db, task)
    task.retired_at = None
    task.retired_reason = None
    await db.flush()
    return task


async def ensure_can_retire(db: AsyncSession, task: Task) -> None:
    """Validate retirement after the caller has locked ``task`` FOR UPDATE."""
    if task.retired_at is not None:
        raise HTTPException(409, "La tarea ya está retirada")
    if task.is_recurring:
        raise HTTPException(409, "Pausa o cierra la recurrencia para conservar su calendario")
    active_timer = await db.scalar(select(TimeEntry.id).where(
        TimeEntry.task_id == task.id, TimeEntry.minutes.is_(None),
    ).limit(1))
    if active_timer is not None:
        raise HTTPException(409, "Detén el timer antes de retirar la tarea")
    active_dependent = await db.scalar(select(Task.id).where(
        Task.depends_on == task.id,
        Task.retired_at.is_(None),
        Task.status != TaskStatus.completed,
    ).order_by(Task.id).limit(1))
    if active_dependent is not None:
        raise HTTPException(409, "La tarea tiene dependencias activas; revísalas antes de retirarla")


async def ensure_can_restore(db: AsyncSession, task: Task) -> None:
    """Validate restoration and lock its dependency against retirement."""
    if task.retired_at is None:
        raise HTTPException(409, "La tarea ya está activa")
    if task.is_recurring:
        raise HTTPException(409, "Gestiona esta plantilla desde su configuración de recurrencia")
    if task.status == TaskStatus.completed or task.depends_on is None:
        return
    dependency = (await db.execute(
        select(Task.id, Task.retired_at)
        .where(Task.id == task.depends_on)
        .with_for_update(read=True, key_share=True)
    )).one_or_none()
    if dependency is None:
        raise HTTPException(409, "La tarea de la que dependía ya no existe")
    if dependency.retired_at is not None:
        raise HTTPException(409, "Restaura primero la tarea de la que depende")
