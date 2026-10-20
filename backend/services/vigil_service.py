"""Copia el resumen de Vigil (cambios en las webs de los clientes).

Vigil expone ``GET /api/integrations/summary`` con una clave de servicio y
devuelve todos sus clientes activos. Se guarda una fila por slug en
``vigil_summary``; los clientes de The Agency se enlazan por ``vigil_slug``.
Nada se borra si la llamada falla: la ficha sigue enseñando el último resumen
con su fecha.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from backend.config import settings
from backend.db.models import VigilSummary

logger = logging.getLogger(__name__)

SUMMARY_DAYS = 7
# Un resumen más viejo que esto no cuenta en el estado del cliente: si Vigil
# deja de responder, mejor "sin dato" que un aviso de hace una semana.
STALE_AFTER_HOURS = 48


def configured() -> bool:
    return bool(settings.VIGIL_API_URL and settings.VIGIL_SERVICE_KEY)


async def fetch_summary(*, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    url = f"{settings.VIGIL_API_URL.rstrip('/')}/api/integrations/summary"
    async with httpx.AsyncClient(timeout=30.0, transport=transport) as http:
        response = await http.get(
            url, params={"days": SUMMARY_DAYS},
            headers={"X-Service-Key": settings.VIGIL_SERVICE_KEY},
        )
        response.raise_for_status()
        return response.json()["clients"]


async def sync(session_factory, *, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Sustituye los resúmenes por los de Vigil. Devuelve cuántos clientes llegaron."""
    clients = await fetch_summary(transport=transport)
    now = datetime.now(timezone.utc)
    slugs = [c["slug"] for c in clients]
    async with session_factory() as db:
        for c in clients:
            await db.execute(insert(VigilSummary).values(slug=c["slug"], data=c, fetched_at=now)
                             .on_conflict_do_update(index_elements=[VigilSummary.slug],
                                                    set_={"data": c, "fetched_at": now}))
        # Un cliente desactivado en Vigil deja de salir: su resumen se va con él.
        await db.execute(delete(VigilSummary).where(VigilSummary.slug.notin_(slugs)))
        await db.commit()
    logger.info("Vigil: %d clientes sincronizados", len(clients))
    return len(clients)


async def summaries(db, slugs: set[str]) -> dict[str, VigilSummary]:
    if not slugs:
        return {}
    rows = (await db.scalars(select(VigilSummary).where(VigilSummary.slug.in_(slugs)))).all()
    return {r.slug: r for r in rows}


def client_block(row: VigilSummary, *, now: datetime | None = None) -> dict:
    """Lo que enseña la ficha. ``fresh`` dice si cuenta para el estado."""
    now = now or datetime.now(timezone.utc)
    data = row.data
    pending = data.get("changes_unacknowledged") or {}
    run = data.get("last_run") or {}
    return {
        "slug": row.slug,
        "critical": int(pending.get("critical", 0)),
        "warning": int(pending.get("warning", 0)),
        "info": int(pending.get("info", 0)),
        "watches_active": int(data.get("watches_active") or 0),
        "watches_with_error": int(data.get("watches_with_error") or 0),
        "last_checked_at": data.get("last_checked_at"),
        "last_run_status": run.get("status"),
        "fetched_at": row.fetched_at.isoformat(),
        "fresh": (now - row.fetched_at).total_seconds() <= STALE_AFTER_HOURS * 3600,
        "url": settings.VIGIL_FRONTEND_URL,
    }
