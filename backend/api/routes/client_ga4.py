"""GA4 en vivo de un cliente (`services/ga4_live.py`), para el MCP.

Sólo lectura del módulo `clients`, con el mismo 404 que `/{id}/status`. No
guarda nada: cada llamada pregunta a Google. `query` es POST porque lleva una
lista de filtros; no cambia nada (como `runReport` de la Data API).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.core.rate_limiter import ga4_live_limiter
from backend.db.database import get_db
from backend.db.models import User
from backend.services import ga4_live

router = APIRouter(prefix="/api/clients", tags=["client-ga4"])

# Por persona; cada consulta son dos llamadas a Google.
LIMIT_PER_MINUTE = 60


class Ga4Filter(BaseModel):
    dimension: ga4_live.Dimension
    operator: ga4_live.Operator
    expression: str = Field(min_length=1, max_length=4096)


class Ga4OrderBy(BaseModel):
    # Una de las dimensiones o métricas pedidas (lo comprueba el servicio).
    field: str = Field(min_length=1, max_length=100)
    desc: bool = False


class Ga4QueryRequest(BaseModel):
    start_date: date
    end_date: date
    dimensions: list[ga4_live.Dimension] = Field(default_factory=list, max_length=ga4_live.MAX_DIMENSIONS)
    metrics: list[ga4_live.Metric] = Field(min_length=1, max_length=ga4_live.MAX_METRICS)
    filters: list[Ga4Filter] = Field(default_factory=list, max_length=20)
    limit: int = Field(1000, ge=1, le=ga4_live.MAX_LIMIT)
    offset: int = Field(0, ge=0)
    order_by: list[Ga4OrderBy] = Field(default_factory=list, max_length=5)
    property_id: Optional[str] = Field(None, max_length=40)

    @field_validator("dimensions", "metrics")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Cada dimensión o métrica sólo puede ir una vez")
        return value


def _http(exc: ga4_live.Ga4LiveError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/{client_id}/ga4/properties")
async def client_ga4_properties(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """Propiedad de GA4 del cliente, la cuenta que la ve y el último día con datos."""
    client = await get_client_or_404(client_id, db)
    ga4_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await ga4_live.properties(db, client)
    except ga4_live.Ga4LiveError as exc:
        raise _http(exc) from exc


@router.post("/{client_id}/ga4/query")
async def client_ga4_query(
    client_id: int,
    body: Ga4QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """`runReport` de la Data API de GA4 con los totales del mismo informe."""
    client = await get_client_or_404(client_id, db)
    ga4_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await ga4_live.query(
            db, client,
            start_date=body.start_date, end_date=body.end_date, dimensions=body.dimensions,
            metrics=body.metrics, filters=[f.model_dump() for f in body.filters],
            limit=body.limit, offset=body.offset, order_by=[o.model_dump() for o in body.order_by],
            property_id=body.property_id,
        )
    except ga4_live.Ga4LiveError as exc:
        raise _http(exc) from exc
