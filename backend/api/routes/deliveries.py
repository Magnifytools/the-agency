from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import CommunicationRequest, Delivery, User, UserRole
from backend.schemas.delivery import DeliveryReceipt, ResendRequest
from backend.services import deliveries as service

router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])


def writable(actor, kind):
    if kind not in service.SOURCE_MODELS:
        return False
    if kind == "daily" or actor.role == UserRole.admin:
        return True
    module = "pm" if kind == "communication" else "digests"
    return any(p.module == module and p.can_write for p in actor.permissions)


@router.get("", response_model=list[DeliveryReceipt])
async def list_deliveries(source_kind: str, source_id: int, limit: int = Query(10, ge=1, le=50), db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    source = await service.authorize_source(db, source_kind, source_id, actor, write=False)
    rows = (await db.execute(select(Delivery).where(Delivery.source_kind == source_kind, Delivery.source_id == source_id).order_by(Delivery.created_at.desc(), Delivery.id).limit(limit))).scalars().all()
    return [await service.receipt(db, row, source, writable=writable(actor, source_kind)) for row in rows]


@router.get("/manual", response_model=list[DeliveryReceipt])
async def list_manual_deliveries(kind: str, scope: str | None = None, limit: int = Query(10, ge=1, le=50),
                                 db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    from backend.services.manual_communications import KINDS, authorize_request
    from types import SimpleNamespace
    authorize_request(SimpleNamespace(kind=kind, scope=scope or ("mine" if kind == "pm_briefing" else "team"),
                      owner_id=actor.id, destination_kind="owner_dm" if kind == "weekly_report" else "team_webhook"), actor, write=False)
    if kind not in KINDS:
        raise HTTPException(404, "Fuente no encontrada")
    query = select(Delivery, CommunicationRequest).join(CommunicationRequest,
        (Delivery.source_kind == "communication") & (Delivery.source_id == CommunicationRequest.id)
    ).where(CommunicationRequest.owner_id == actor.id, CommunicationRequest.kind == kind)
    if scope is not None:
        query = query.where(CommunicationRequest.scope == scope)
    rows = (await db.execute(query.order_by(Delivery.created_at.desc(), Delivery.id).limit(limit))).all()
    return [await service.receipt(db, row, source, writable=writable(actor, "communication")) for row, source in rows]


@router.get("/{delivery_id}", response_model=DeliveryReceipt)
async def get_delivery(delivery_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row, source = await service.load_delivery(db, delivery_id, actor)
    return await service.receipt(db, row, source, writable=writable(actor, row.source_kind))


@router.post("/{delivery_id}/retry", response_model=DeliveryReceipt, status_code=202)
async def retry_delivery(delivery_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row, source = await service.load_delivery(db, delivery_id, actor, write=True, lock=True)
    await service.retry(db, row, source)
    return await service.receipt(db, row, source)


@router.post("/{delivery_id}/cancel", response_model=DeliveryReceipt)
async def cancel_delivery(delivery_id: str, db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row, source = await service.load_delivery(db, delivery_id, actor, write=True, lock=True)
    if row.status != "pending":
        raise HTTPException(409, "Solo se puede cancelar un envío aún en cola")
    row.status, row.message = "cancelled", "Cancelado antes del envío; borrador conservado"
    await db.commit()
    return await service.receipt(db, row, source)


@router.post("/{delivery_id}/resend", response_model=DeliveryReceipt, status_code=202)
async def resend_delivery(delivery_id: str, body: ResendRequest, db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    row, source = await service.load_delivery(db, delivery_id, actor, write=True, lock=True)
    replacement = await service.resend(db, row, source, actor, body.review_key)
    return await service.receipt(db, replacement, source)
