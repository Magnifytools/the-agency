"""GA4 propio: estado de la importación por propiedad y botón de importar ahora."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_admin, require_module
from backend.db.database import async_session, get_db
from backend.db.models import Client, ClientStatus, Ga4PropertySync, GscConnection, User
from backend.services import ga4_service

router = APIRouter(prefix="/api/ga4", tags=["ga4"])


@router.get("/status")
async def ga4_status(db: AsyncSession = Depends(get_db), _: User = Depends(require_module("clients"))):
    """Propiedades GA4 de los clientes activos y cómo va su importación."""
    clients = (await db.execute(
        select(Client.id, Client.name, Client.ga4_property_id)
        .where(Client.status == ClientStatus.active, Client.ga4_property_id.isnot(None))
        .order_by(Client.name)
    )).all()
    by_prop: dict[str, list[dict]] = {}
    for row in clients:
        pid = ga4_service.normalize_property(row.ga4_property_id)
        if pid:
            by_prop.setdefault(pid, []).append({"id": row.id, "name": row.name})
    states = {s.property_id: s for s in (await db.scalars(
        select(Ga4PropertySync).where(Ga4PropertySync.property_id.in_(list(by_prop)))
    )).all()} if by_prop else {}
    emails = dict((await db.execute(select(GscConnection.id, GscConnection.google_email))).all())
    return {
        "configured": ga4_service.configured(),
        "properties": [
            {
                "property_id": pid,
                "clients": by_prop[pid],
                "last_data_date": states[pid].last_data_date if pid in states else None,
                "last_synced_at": states[pid].last_synced_at if pid in states else None,
                "error_code": states[pid].error_code if pid in states else None,
                "google_email": emails.get(states[pid].connection_id) if pid in states else None,
            }
            for pid in sorted(by_prop)
        ],
    }


@router.post("/sync")
async def ga4_sync(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Importa ahora en vez de esperar a la pasada diaria."""
    if not ga4_service.configured():
        raise HTTPException(status_code=503, detail="Google OAuth no está configurado")
    await db.commit()
    return await ga4_service.sync_all(async_session)
