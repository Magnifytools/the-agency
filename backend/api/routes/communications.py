from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import CommunicationLog, Client, User, UserRole, CommunicationChannel, CommunicationDirection
from backend.schemas.communication import CommunicationCreate, CommunicationUpdate, CommunicationResponse
from backend.api.deps import get_current_user, require_module

router = APIRouter(prefix="/api", tags=["communications"])


def _to_response(comm: CommunicationLog) -> CommunicationResponse:
    return CommunicationResponse(
        id=comm.id,
        channel=comm.channel.value,
        direction=comm.direction.value,
        subject=comm.subject,
        summary=comm.summary,
        contact_name=comm.contact_name,
        occurred_at=comm.occurred_at,
        requires_followup=comm.requires_followup,
        followup_date=comm.followup_date,
        followup_notes=comm.followup_notes,
        client_id=comm.client_id,
        user_id=comm.user_id,
        user_name=comm.user.full_name if comm.user else None,
        created_at=comm.created_at,
        updated_at=comm.updated_at,
    )


@router.get("/clients/{client_id}/communications", response_model=list[CommunicationResponse])
async def list_client_communications(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("communications")),
):
    """List all communications for a client, ordered by most recent first."""
    result = await db.execute(
        select(CommunicationLog)
        .where(CommunicationLog.client_id == client_id)
        .order_by(CommunicationLog.occurred_at.desc())
    )
    return [_to_response(c) for c in result.scalars().all()]


@router.post("/clients/{client_id}/communications", response_model=CommunicationResponse, status_code=status.HTTP_201_CREATED)
async def create_communication(
    client_id: int,
    body: CommunicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("communications", write=True)),
):
    """Create a new communication log entry for a client."""
    # Verify client exists
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")

    comm = CommunicationLog(
        channel=CommunicationChannel(body.channel),
        direction=CommunicationDirection(body.direction),
        subject=body.subject,
        summary=body.summary,
        contact_name=body.contact_name,
        occurred_at=body.occurred_at,
        requires_followup=body.requires_followup,
        followup_date=body.followup_date,
        followup_notes=body.followup_notes,
        client_id=client_id,
        user_id=current_user.id,
    )
    db.add(comm)
    await db.commit()
    await db.refresh(comm)
    return _to_response(comm)


# Static path BEFORE dynamic {comm_id} to avoid 422
@router.get("/communications/pending-followups", response_model=list[CommunicationResponse])
async def list_pending_followups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("communications")),
):
    """List all communications that require follow-up and haven't been addressed."""
    query = select(CommunicationLog).where(CommunicationLog.requires_followup.is_(True))
    # F-06: members see only their own followups
    if current_user.role != UserRole.admin:
        query = query.where(CommunicationLog.user_id == current_user.id)
    query = query.order_by(CommunicationLog.followup_date.asc())
    result = await db.execute(query)
    return [_to_response(c) for c in result.scalars().all()]


@router.get("/communications/{comm_id}", response_model=CommunicationResponse)
async def get_communication(
    comm_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("communications")),
):
    result = await db.execute(select(CommunicationLog).where(CommunicationLog.id == comm_id))
    comm = result.scalar_one_or_none()
    if not comm:
        raise HTTPException(status_code=404, detail="Communication not found")
    return _to_response(comm)


@router.put("/communications/{comm_id}", response_model=CommunicationResponse)
async def update_communication(
    comm_id: int,
    body: CommunicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("communications", write=True)),
):
    result = await db.execute(select(CommunicationLog).where(CommunicationLog.id == comm_id))
    comm = result.scalar_one_or_none()
    if not comm:
        raise HTTPException(status_code=404, detail="Communication not found")
    # F-06: members can only edit their own communications
    if current_user.role != UserRole.admin and comm.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your communication")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "channel" and value:
            value = CommunicationChannel(value)
        elif field == "direction" and value:
            value = CommunicationDirection(value)
        elif field == "requires_followup":
            value = bool(value)
        setattr(comm, field, value)

    await db.commit()
    await db.refresh(comm)
    return _to_response(comm)


@router.delete("/communications/{comm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_communication(
    comm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("communications", write=True)),
):
    result = await db.execute(select(CommunicationLog).where(CommunicationLog.id == comm_id))
    comm = result.scalar_one_or_none()
    if not comm:
        raise HTTPException(status_code=404, detail="Communication not found")
    # F-06: members can only delete their own communications
    if current_user.role != UserRole.admin and comm.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your communication")
    await db.delete(comm)
    await db.commit()
