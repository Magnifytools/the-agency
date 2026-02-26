from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Client, ClientStatus, Task, TimeEntry, User
from backend.schemas.client import ClientCreate, ClientUpdate, ClientResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module
from backend.services.client_health import compute_health, compute_health_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("", response_model=PaginatedResponse[ClientResponse])
async def list_clients(
    status_filter: Optional[ClientStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    base = select(Client)
    if status_filter:
        base = base.where(Client.status == status_filter)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    query = base.order_by(Client.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)

    return PaginatedResponse(items=result.scalars().all(), total=total, page=page, page_size=page_size)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    client = Client(**body.model_dump())
    db.add(client)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un cliente con esos datos")
    except Exception as e:
        await db.rollback()
        logger.error("Error creando cliente: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await db.refresh(client)
    return client


@router.get("/health-scores")
async def list_health_scores(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Health scores for all active clients."""
    result = await db.execute(
        select(Client).where(Client.status == ClientStatus.active).order_by(Client.name)
    )
    clients = result.scalars().all()
    scores = await compute_health_batch(clients, db)
    # Sort by score ascending (worst first)
    scores.sort(key=lambda s: s["score"])
    return scores


@router.get("/{client_id}/health")
async def get_client_health(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Health score for a single client."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return await compute_health(client, db)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al actualizar cliente")
    except Exception as e:
        await db.rollback()
        logger.error("Error actualizando cliente %d: %s", client_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await db.refresh(client)
    return client


@router.delete("/{client_id}", response_model=ClientResponse)
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    client.status = ClientStatus.finished
    await db.commit()
    await db.refresh(client)
    return client


@router.get("/{client_id}/summary")
async def get_client_summary(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Fetch tasks
    tasks_result = await db.execute(
        select(Task).where(Task.client_id == client_id).order_by(Task.created_at.desc())
    )
    tasks = tasks_result.scalars().all()

    # Aggregate time
    time_result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.task_id.in_([t.id for t in tasks]),
            TimeEntry.minutes.isnot(None),
        )
    )
    total_tracked_minutes = time_result.scalar()

    total_estimated = sum(t.estimated_minutes or 0 for t in tasks)
    total_actual = sum(t.actual_minutes or 0 for t in tasks)

    from backend.schemas.task import TaskResponse
    from backend.api.routes.tasks import _task_to_response

    return {
        "client": ClientResponse.model_validate(client),
        "tasks": [_task_to_response(t) for t in tasks],
        "total_tasks": len(tasks),
        "total_estimated_minutes": total_estimated,
        "total_actual_minutes": total_actual,
        "total_tracked_minutes": total_tracked_minutes,
    }


@router.post("/{client_id}/ai-advice")
async def get_ai_advice(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    """Get AI-generated recommendations for a client."""
    from backend.services.client_advisor import get_client_advice
    try:
        recommendations = await get_client_advice(db, client_id)
        return {"recommendations": recommendations}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
