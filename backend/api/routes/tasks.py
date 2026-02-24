from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Task, TaskStatus, User
from backend.schemas.task import TaskCreate, TaskUpdate, TaskResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        estimated_minutes=task.estimated_minutes,
        actual_minutes=task.actual_minutes,
        due_date=task.due_date,
        client_id=task.client_id,
        category_id=task.category_id,
        assigned_to=task.assigned_to,
        project_id=task.project_id,
        phase_id=task.phase_id,
        depends_on=task.depends_on,
        created_at=task.created_at,
        updated_at=task.updated_at,
        client_name=task.client.name if task.client else None,
        category_name=task.category.name if task.category else None,
        assigned_user_name=task.assigned_user.full_name if task.assigned_user else None,
        project_name=task.project.name if task.project else None,
        phase_name=task.phase.name if task.phase else None,
    )


@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    client_id: Optional[int] = Query(None),
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    category_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    base = select(Task)
    if client_id is not None:
        base = base.where(Task.client_id == client_id)
    if status_filter is not None:
        base = base.where(Task.status == status_filter)
    if category_id is not None:
        base = base.where(Task.category_id == category_id)
    if project_id is not None:
        base = base.where(Task.project_id == project_id)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    query = base.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)

    return PaginatedResponse(
        items=[_task_to_response(t) for t in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    task = Task(**body.model_dump())
    db.add(task)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al crear tarea (datos duplicados o referencia inválida)")
    except Exception as e:
        await db.rollback()
        logger.error("Error creando tarea: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await db.refresh(task)
    return _task_to_response(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al actualizar tarea")
    except Exception as e:
        await db.rollback()
        logger.error("Error actualizando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await db.refresh(task)
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        await db.delete(task)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede eliminar: tiene registros asociados")
    except Exception as e:
        await db.rollback()
        logger.error("Error eliminando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
