"""Bloques de trabajo con hora (Mi agenda, vista con horas).

Cada persona ve y toca sólo los suyos. Leer pide lectura de ``tasks`` y
cambiarlos, escritura (como mover una tarea de día). Horas civiles de la
agencia sin zona, como los eventos de Google Calendar importados.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import Client, Task, TaskStatus, TaskTimeBlock, User
from backend.schemas.time_block import TimeBlockCreate, TimeBlockResponse, TimeBlockUpdate

router = APIRouter(prefix="/api/time-blocks", tags=["time-blocks"])

MAX_RANGE_DAYS = 14
MAX_BLOCK = timedelta(hours=12)


def _response(block: TaskTimeBlock, title: str, status, estimated_minutes, client_name) -> TimeBlockResponse:
    return TimeBlockResponse(
        id=block.id, task_id=block.task_id, starts_at=block.starts_at, ends_at=block.ends_at,
        task_title=title, task_status=getattr(status, "value", status),
        task_estimated_minutes=estimated_minutes, client_name=client_name,
    )


def _task_response(block: TaskTimeBlock, task: Task) -> TimeBlockResponse:
    return _response(block, task.title, task.status, task.estimated_minutes, task.client.name if task.client else None)


def _check_times(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    if starts_at.tzinfo or ends_at.tzinfo:
        raise HTTPException(422, "Indica la hora civil de la agencia, sin zona horaria")
    starts_at, ends_at = starts_at.replace(second=0, microsecond=0), ends_at.replace(second=0, microsecond=0)
    if ends_at <= starts_at:
        raise HTTPException(422, "El bloque tiene que terminar después de empezar")
    if ends_at - starts_at > MAX_BLOCK:
        raise HTTPException(422, "Un bloque dura como mucho 12 horas")
    if (ends_at - timedelta(microseconds=1)).date() != starts_at.date():
        raise HTTPException(422, "Un bloque empieza y acaba el mismo día")
    return starts_at, ends_at


async def _plannable_task(db: AsyncSession, task_id: int) -> Task:
    task = (await db.execute(
        select(Task).options(noload("*"), selectinload(Task.client)).where(Task.id == task_id)
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.is_recurring:
        raise HTTPException(422, "Una plantilla recurrente no se planifica: planifica sus repeticiones")
    if task.retired_at is not None:
        raise HTTPException(409, "Restaura la tarea antes de planificarla")
    return task


async def _own_block(db: AsyncSession, block_id: int, user: User) -> TaskTimeBlock:
    block = (await db.execute(
        select(TaskTimeBlock).where(TaskTimeBlock.id == block_id, TaskTimeBlock.user_id == user.id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if block is None:
        raise HTTPException(404, "Bloque no encontrado")
    return block


@router.get("", response_model=list[TimeBlockResponse])
async def list_time_blocks(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("tasks")),
):
    """Mis bloques entre dos días civiles (ambos incluidos, como mucho 14)."""
    if date_to < date_from or (date_to - date_from).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, "Pide entre 1 y 14 días")
    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    rows = (await db.execute(
        select(TaskTimeBlock, Task.title, Task.status, Task.estimated_minutes, Client.name)
        .join(Task, Task.id == TaskTimeBlock.task_id)
        .outerjoin(Client, Client.id == Task.client_id)
        .where(TaskTimeBlock.user_id == user.id, TaskTimeBlock.starts_at >= start, TaskTimeBlock.starts_at < end)
        .order_by(TaskTimeBlock.starts_at, TaskTimeBlock.id)
    )).all()
    return [_response(*row) for row in rows]


@router.post("", response_model=TimeBlockResponse, status_code=201)
async def create_time_block(
    body: TimeBlockCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("tasks", write=True)),
):
    starts_at, ends_at = _check_times(body.starts_at, body.ends_at)
    task = await _plannable_task(db, body.task_id)
    if task.status == TaskStatus.completed:
        raise HTTPException(422, "La tarea ya está hecha")
    block = TaskTimeBlock(task_id=task.id, user_id=user.id, starts_at=starts_at, ends_at=ends_at)
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return _task_response(block, task)


@router.patch("/{block_id}", response_model=TimeBlockResponse)
async def update_time_block(
    block_id: int,
    body: TimeBlockUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("tasks", write=True)),
):
    block = await _own_block(db, block_id, user)
    starts_at, ends_at = _check_times(body.starts_at or block.starts_at, body.ends_at or block.ends_at)
    task = await _plannable_task(db, block.task_id)
    block.starts_at, block.ends_at = starts_at, ends_at
    await db.commit()
    await db.refresh(block)
    return _task_response(block, task)


@router.delete("/{block_id}", status_code=204)
async def delete_time_block(
    block_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("tasks", write=True)),
):
    block = await _own_block(db, block_id, user)
    await db.delete(block)
    await db.commit()
