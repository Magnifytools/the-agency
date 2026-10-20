"""Vigil: qué clientes tiene (para enlazarlos en Ajustes del cliente)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import Client, User, VigilSummary
from backend.services import vigil_service

router = APIRouter(prefix="/api/vigil", tags=["vigil"])


@router.get("/clients")
async def vigil_clients(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("clients")),
):
    """Clientes de Vigil del último resumen y a qué cliente de aquí están enlazados."""
    rows = (await db.scalars(select(VigilSummary).order_by(VigilSummary.slug))).all()
    linked = dict((await db.execute(
        select(Client.vigil_slug, Client.name).where(Client.vigil_slug.isnot(None))
    )).all())
    return {
        "configured": vigil_service.configured(),
        "clients": [
            {"slug": r.slug, "name": r.data.get("name") or r.slug, "linked_to": linked.get(r.slug)}
            for r in rows
        ],
    }
