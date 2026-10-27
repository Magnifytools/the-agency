"""Control SEO por cliente: lectura del tráfico de Google por marca, sección,
consulta y página (`services/seo_control.py`).

Sólo lectura del módulo `clients`, con el mismo 404 que `/{id}/status`.
También los leads por landing de GA4 (`/{id}/leads`, `services/ga4_leads.py`).
Fuera del MCP y de la IA a propósito: el detalle de Search Console no sale de
la app (política de privacidad).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_module
from backend.db.database import get_db
from backend.db.models import Client, SeoAnnotation, User
from backend.services import ga4_leads, seo_control, seo_insights

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
    group: Optional[str] = Query(None, max_length=seo_control.MAX_GROUP_NAME),
    q: Optional[str] = Query(None, max_length=200),
    min_impressions: int = Query(seo_control.DEFAULT_MIN_IMPRESSIONS, ge=0, le=1_000_000),
    limit: int = Query(25, ge=1, le=seo_control.MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    client = await _client_or_404(db, client_id, days)
    try:
        return await seo_control.movers(
            db, client, "page", days=days, sort=sort, section=section, group=group, q=q,
            min_impressions=min_impressions, limit=limit,
        )
    except seo_control.PageGroupTimeout:
        raise HTTPException(status_code=422, detail=_GROUPS_TOO_SLOW)


@router.get("/{client_id}/seo/queries/history")
async def client_seo_query_history(
    client_id: int,
    query: str = Query(..., min_length=1, max_length=1000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Historial de una consulta: meses guardados (hasta 16) y días del detalle (120)."""
    client = await _client_or_404(db, client_id, seo_control.SEO_WINDOW_DAYS)
    return await seo_control.query_history(db, client, query)


_GROUPS_TOO_SLOW = "Las reglas de los grupos tardan demasiado; simplifica las regex"


@router.get("/{client_id}/seo/groups")
async def client_seo_groups(
    client_id: int,
    days: int = Query(seo_control.SEO_WINDOW_DAYS),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Clics, impresiones y posición por grupo de URL del cliente."""
    client = await _client_or_404(db, client_id, days)
    try:
        return await seo_control.page_groups(db, client, days=days)
    except seo_control.PageGroupTimeout:
        raise HTTPException(status_code=422, detail=_GROUPS_TOO_SLOW)


class GroupsPreview(BaseModel):
    groups: list

    @field_validator("groups", mode="before")
    @classmethod
    def _groups(cls, value):
        return seo_control.clean_page_groups(value)


@router.post("/{client_id}/seo/groups/preview")
async def client_seo_groups_preview(
    client_id: int,
    body: GroupsPreview,
    days: int = Query(seo_control.SEO_WINDOW_DAYS),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Prueba unos grupos SIN guardarlos: cuántas páginas y clics recoge cada uno.

    Sólo lee (POST porque los grupos van en el cuerpo); guardar es el PUT del cliente.
    """
    client = await _client_or_404(db, client_id, days)
    try:
        return await seo_control.page_groups(db, client, days=days, groups=body.groups)
    except seo_control.PageGroupTimeout:
        raise HTTPException(status_code=422, detail=_GROUPS_TOO_SLOW)


@router.get("/{client_id}/leads")
async def client_leads(
    client_id: int,
    days: int = Query(ga4_leads.WINDOW_CHOICES[-1]),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Leads por landing (GA4): total, landings con más leads y canales, frente
    a la ventana anterior. Lo pinta la Vista general de la ficha."""
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    if days not in ga4_leads.WINDOW_CHOICES:
        raise HTTPException(status_code=422, detail="La ventana es de 7 o 28 días")
    return await ga4_leads.client_leads(db, client, days=days)


# ── Anotaciones, antes/después y páginas que pierden tráfico (bloque B) ──

ANNOTATION_MAX_DAYS = 800


async def _client(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{client_id}/seo/annotations")
async def client_seo_annotations(
    client_id: int,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients")),
):
    """Notas, actualizaciones de Google, cambios críticos de la web y tareas
    publicadas entre dos fechas, para pintarlas sobre las gráficas."""
    client = await _client(db, client_id)
    if end < start or (end - start).days > ANNOTATION_MAX_DAYS:
        raise HTTPException(status_code=422, detail="Rango de fechas no válido")
    return await seo_insights.annotations(db, client, user, start, end)


class AnnotationCreate(BaseModel):
    date: date
    text: str = Field(min_length=1, max_length=160)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Escribe la nota")
        return value


@router.post("/{client_id}/seo/annotations", status_code=201)
async def create_seo_annotation(
    client_id: int,
    body: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients", write=True)),
):
    await _client(db, client_id)
    if body.date > date.today() + timedelta(days=1):
        raise HTTPException(status_code=422, detail="La nota no puede ser de una fecha futura")
    annotation = SeoAnnotation(client_id=client_id, date=body.date, text=body.text, created_by=user.id)
    db.add(annotation)
    await db.commit()
    return {"id": annotation.id, "date": annotation.date.isoformat(), "text": annotation.text}


@router.delete("/{client_id}/seo/annotations/{annotation_id}", status_code=204)
async def delete_seo_annotation(
    client_id: int,
    annotation_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    annotation = await db.get(SeoAnnotation, annotation_id)
    if annotation is None or annotation.client_id != client_id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    await db.delete(annotation)
    await db.commit()
    return Response(status_code=204)


@router.get("/{client_id}/seo/impact")
async def client_seo_impact(
    client_id: int,
    pivot: date = Query(..., alias="date"),
    days: int = Query(28),
    page: Optional[str] = Query(None, max_length=2000),
    group: Optional[str] = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Antes y después de una fecha: la web entera, una página o un grupo de URL."""
    client = await _client(db, client_id)
    if days not in seo_insights.IMPACT_DAY_CHOICES:
        raise HTTPException(status_code=422, detail="Compara 14, 28 o 56 días")
    if page and group:
        raise HTTPException(status_code=422, detail="Elige una página o un grupo, no los dos")
    if page and not seo_insights.page_variants(page):
        raise HTTPException(status_code=422, detail="La página tiene que ser una URL completa (https://…)")
    try:
        return await seo_insights.impact(db, client, pivot=pivot, days=days, page=page, group=group)
    except seo_control.PageGroupTimeout:
        raise HTTPException(status_code=422, detail=_GROUPS_TOO_SLOW)


@router.get("/{client_id}/seo/decay")
async def client_seo_decay(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Páginas muy por debajo de su mejor tramo de 28 días (detalle de 120 días)."""
    client = await _client(db, client_id)
    return await seo_insights.decaying_pages(db, client)
