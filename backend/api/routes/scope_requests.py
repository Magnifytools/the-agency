"""Peticiones fuera de alcance de un cliente (pestaña "Peticiones extra").

Leer: lectura de ``clients``. Escribir (apuntar, decidir, borrar): escritura de
``clients``. Es una decisión comercial sobre el cliente (absorber o facturar),
existe sin proyecto y vive en su ficha; los permisos de ``projects`` no cubren
una petición sin proyecto, así que no sirven de puerta. Entra en el Deshacer.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import ClientScopeRequest, User
from backend.schemas.scope_request import (
    ScopeRequestCreate, ScopeRequestList, ScopeRequestResponse, ScopeRequestUpdate,
)
from backend.services import scope_requests as service

router = APIRouter(prefix="/api/clients/{client_id}/scope-requests", tags=["scope-requests"])


@router.get("", response_model=ScopeRequestList)
async def list_scope_requests(
    client_id: int,
    month: Optional[str] = Query(None, description="AAAA-MM; sin él, el mes actual"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients")),
):
    await service.require_client(db, client_id)
    try:
        return await service.list_for_month(db, client_id, month, actor=user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=ScopeRequestResponse, status_code=201)
async def create_scope_request(
    client_id: int,
    body: ScopeRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients", write=True)),
):
    row = await service.create_scope_request(db, actor=user, client_id=client_id, data=body.model_dump())
    await db.commit()
    return await service.load_one(db, client_id, row.id, actor=user)


async def _locked(db: AsyncSession, client_id: int, request_id: int) -> ClientScopeRequest:
    row = (await db.execute(select(ClientScopeRequest).where(
        ClientScopeRequest.id == request_id, ClientScopeRequest.client_id == client_id,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Petición no encontrada")
    return row


@router.patch("/{request_id}", response_model=ScopeRequestResponse)
async def update_scope_request(
    client_id: int,
    request_id: int,
    body: ScopeRequestUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients", write=True)),
):
    row = await _locked(db, client_id, request_id)
    data = body.model_dump(exclude_unset=True)
    for required in ("title", "estimated_minutes", "requested_on", "decision"):
        if required in data and data[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} no puede quedar vacío")
    if "project_id" in data:
        await service.validate_project(db, user, client_id, data["project_id"])
        row.project_id = data["project_id"]
    for field in ("title", "detail", "estimated_minutes", "requested_on", "decision_note"):
        if field in data:
            setattr(row, field, data[field])
    if "decision" in data:
        service.apply_decision(row, data["decision"], user)
    await db.commit()
    return await service.load_one(db, client_id, request_id, actor=user)


@router.delete("/{request_id}", status_code=204)
async def delete_scope_request(
    client_id: int,
    request_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    row = await _locked(db, client_id, request_id)
    await db.delete(row)
    await db.commit()
