from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.api.deps import require_module
from backend.api.utils.db_helpers import safe_refresh
from backend.db.database import get_db
from backend.db.models import Client, ClientContact, User
from backend.schemas.contact import ContactCreate, ContactResponse, ContactUpdate
from backend.services.domain_writes import create_contact as create_contact_write

router = APIRouter(prefix="/api/clients/{client_id}/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactResponse])
async def list_contacts(
    client_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(
        select(ClientContact)
        .where(ClientContact.client_id == client_id)
        .order_by(ClientContact.is_primary.desc(), ClientContact.name)
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.post("", response_model=ContactResponse, status_code=201)
async def create_contact(
    client_id: int,
    body: ContactCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    contact = await create_contact_write(db, client_id, body.model_dump())
    await db.commit()
    await safe_refresh(db, contact, log_context="contacts")
    return contact


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    client_id: int,
    contact_id: int,
    body: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    locked_client_id = await db.scalar(
        select(Client.id).where(Client.id == client_id).with_for_update()
    )
    if locked_client_id is None:
        raise HTTPException(status_code=404, detail="Client not found")
    result = await db.execute(
        select(ClientContact).where(
            ClientContact.id == contact_id,
            ClientContact.client_id == client_id,
        ).options(noload("*")).with_for_update()
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    data = body.model_dump(exclude_unset=True)

    # If setting as primary, unset other primaries
    if data.get("is_primary"):
        existing = await db.execute(
            select(ClientContact).where(
                ClientContact.client_id == client_id,
                ClientContact.is_primary.is_(True),
                ClientContact.id != contact_id,
            ).order_by(ClientContact.id).options(noload("*")).with_for_update()
        )
        for c in existing.scalars().all():
            c.is_primary = False

    for field, value in data.items():
        setattr(contact, field, value)
    await db.commit()
    await safe_refresh(db, contact, log_context="contacts")
    return contact


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    client_id: int,
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    locked_client_id = await db.scalar(
        select(Client.id).where(Client.id == client_id).with_for_update()
    )
    if locked_client_id is None:
        raise HTTPException(status_code=404, detail="Client not found")
    result = await db.execute(
        select(ClientContact).where(
            ClientContact.id == contact_id,
            ClientContact.client_id == client_id,
        ).options(noload("*")).with_for_update()
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    await db.delete(contact)
    await db.commit()
