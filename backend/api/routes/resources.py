from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, Client, ClientResource
from backend.schemas.resource import ResourceCreate, ResourceUpdate, ResourceResponse
from backend.api.deps import get_current_user, require_module

router = APIRouter(prefix="/api/clients/{client_id}/resources", tags=["resources"])


async def _get_client(client_id: int, db: AsyncSession) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("", response_model=list[ResourceResponse])
async def list_resources(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    await _get_client(client_id, db)
    result = await db.execute(
        select(ClientResource)
        .where(ClientResource.client_id == client_id)
        .order_by(ClientResource.label)
    )
    return result.scalars().all()


@router.post("", response_model=ResourceResponse, status_code=201)
async def create_resource(
    client_id: int,
    body: ResourceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    await _get_client(client_id, db)
    resource = ClientResource(client_id=client_id, **body.model_dump())
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return resource


@router.put("/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    client_id: int,
    resource_id: int,
    body: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(
        select(ClientResource).where(
            ClientResource.id == resource_id,
            ClientResource.client_id == client_id,
        )
    )
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(resource, field, value)
    await db.commit()
    await db.refresh(resource)
    return resource


@router.delete("/{resource_id}", status_code=204)
async def delete_resource(
    client_id: int,
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(
        select(ClientResource).where(
            ClientResource.id == resource_id,
            ClientResource.client_id == client_id,
        )
    )
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    await db.delete(resource)
    await db.commit()
