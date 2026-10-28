"""Search Console en vivo de un cliente (`services/gsc_live.py`), para el MCP.

Sólo lectura del módulo `clients`, con el mismo 404 que `/{id}/status`. No
guarda nada: cada llamada pregunta a Google. `query` es POST porque lleva una
lista de filtros; no cambia nada (como `searchanalytics.query` de Google).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.core.rate_limiter import gsc_live_limiter
from backend.db.database import get_db
from backend.db.models import User
from backend.services import gsc_live

router = APIRouter(prefix="/api/clients", tags=["client-gsc"])

# Por persona; cada consulta son tres llamadas a Google.
LIMIT_PER_MINUTE = 60


class GscFilter(BaseModel):
    dimension: gsc_live.FilterDimension
    operator: gsc_live.Operator
    expression: str = Field(min_length=1, max_length=4096)


class GscQueryRequest(BaseModel):
    start_date: date
    end_date: date
    dimensions: list[gsc_live.Dimension] = Field(default_factory=list, max_length=gsc_live.MAX_DIMENSIONS)
    search_type: gsc_live.SearchType = "web"
    filters: list[GscFilter] = Field(default_factory=list, max_length=20)
    aggregation_type: gsc_live.Aggregation = "auto"
    data_state: gsc_live.DataState = "final"
    row_limit: int = Field(1000, ge=1, le=gsc_live.MAX_ROW_LIMIT)
    start_row: int = Field(0, ge=0)
    property: Optional[str] = Field(None, max_length=300)

    @field_validator("dimensions")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Cada dimensión sólo puede ir una vez")
        return value


def _http(exc: gsc_live.GscLiveError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/{client_id}/gsc/properties")
async def client_gsc_properties(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """Propiedades de Search Console del cliente: la principal y las de su dominio."""
    client = await get_client_or_404(client_id, db)
    gsc_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await gsc_live.properties(db, client)
    except gsc_live.GscLiveError as exc:
        raise _http(exc) from exc


@router.post("/{client_id}/gsc/query")
async def client_gsc_query(
    client_id: int,
    body: GscQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """`searchanalytics.query` de Google para cualquier periodo de los 16 meses."""
    client = await get_client_or_404(client_id, db)
    gsc_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await gsc_live.query(
            db, client,
            start_date=body.start_date, end_date=body.end_date, dimensions=body.dimensions,
            search_type=body.search_type, filters=[f.model_dump() for f in body.filters],
            aggregation_type=body.aggregation_type, data_state=body.data_state,
            row_limit=body.row_limit, start_row=body.start_row, property_url=body.property,
        )
    except gsc_live.GscLiveError as exc:
        raise _http(exc) from exc
