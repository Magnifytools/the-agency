"""Todos los informes SEO locales hechos, para el historial de /digests.

Cada uno se abre en la pestaña "Informe SEO local" de su cliente. Lectura de
``digests``, como la pestaña.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import Client, ClientLocalReport, User
from backend.services.local_report import periods

router = APIRouter(prefix="/api/local-reports", tags=["local-report"])


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


@router.get("")
async def list_local_reports(
    client_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("digests")),
):
    """Versiones de todos los clientes, la más reciente primero (sin datos ni archivos)."""
    deliverer = aliased(User)
    query = (
        select(ClientLocalReport.id, ClientLocalReport.client_id, Client.name.label("client_name"),
               ClientLocalReport.period_start, ClientLocalReport.period_end, ClientLocalReport.file_stem,
               ClientLocalReport.generated_at, ClientLocalReport.delivered_at,
               deliverer.full_name.label("delivered_by_name"), ClientLocalReport.created_at)
        .join(Client, Client.id == ClientLocalReport.client_id)
        .outerjoin(deliverer, deliverer.id == ClientLocalReport.delivered_by)
    )
    if client_id:
        query = query.where(ClientLocalReport.client_id == client_id)
    rows = (await db.execute(
        query.order_by(ClientLocalReport.created_at.desc(), ClientLocalReport.id.desc()).limit(limit).offset(offset)
    )).all()
    return [{
        "id": row.id,
        "client_id": row.client_id,
        "client_name": row.client_name,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "period_label": periods.range_label(row.period_start, row.period_end),
        "file_stem": row.file_stem,
        "generated_at": _iso(row.generated_at),
        "delivered_at": _iso(row.delivered_at),
        "delivered_by_name": row.delivered_by_name,
        "created_at": _iso(row.created_at),
    } for row in rows]
