"""Control SEO por cliente: lectura del tráfico de Google por marca, sección,
consulta y página (`services/seo_control.py`).

Sólo lectura del módulo `clients`, con el mismo 404 que `/{id}/status`.
Fuera del MCP y de la IA a propósito: el detalle de Search Console no sale de
la app (política de privacidad).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import Client, User
from backend.services import seo_control

router = APIRouter(prefix="/api/clients", tags=["client-seo"])


async def _client_or_404(db: AsyncSession, client_id: int, days: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if days not in seo_control.WINDOW_CHOICES:
        raise HTTPException(status_code=422, detail="La ventana es de 7 o 28 días")
    return client


@router.get("/{client_id}/seo")
async def client_seo(
    client_id: int,
    days: int = Query(seo_control.SEO_WINDOW_DAYS),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Resumen: totales, marca/sin marca, secciones y lo que más sube y baja."""
    client = await _client_or_404(db, client_id, days)
    return await seo_control.summary(db, client, days=days)


@router.get("/{client_id}/seo/queries")
async def client_seo_queries(
    client_id: int,
    days: int = Query(seo_control.SEO_WINDOW_DAYS),
    sort: seo_control.MoverSort = Query("clicks_gain"),
    brand: seo_control.BrandFilter = Query("all"),
    q: Optional[str] = Query(None, max_length=200),
    min_impressions: int = Query(seo_control.DEFAULT_MIN_IMPRESSIONS, ge=0, le=1_000_000),
    limit: int = Query(25, ge=1, le=seo_control.MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    client = await _client_or_404(db, client_id, days)
    return await seo_control.movers(
        db, client, "query", days=days, sort=sort, brand=brand, q=q,
        min_impressions=min_impressions, limit=limit,
    )


@router.get("/{client_id}/seo/pages")
async def client_seo_pages(
    client_id: int,
    days: int = Query(seo_control.SEO_WINDOW_DAYS),
    sort: seo_control.MoverSort = Query("clicks_gain"),
    section: Optional[str] = Query(None, max_length=300),
    q: Optional[str] = Query(None, max_length=200),
    min_impressions: int = Query(seo_control.DEFAULT_MIN_IMPRESSIONS, ge=0, le=1_000_000),
    limit: int = Query(25, ge=1, le=seo_control.MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    client = await _client_or_404(db, client_id, days)
    return await seo_control.movers(
        db, client, "page", days=days, sort=sort, section=section, q=q,
        min_impressions=min_impressions, limit=limit,
    )
