"""Search Console propio: detalle por consulta y por página (últimos 120 días).

Complementa a `gsc_service` (totales diarios en `gsc_daily`). Cada día se
importan, por propiedad, las cifras finales por (día, consulta) y por
(día, página) en `gsc_query_daily` y `gsc_page_daily`. Sólo se guardan 120
días: es el detalle para ver qué búsquedas y páginas suben o bajan, no un
histórico.

La cuenta de Google NO se decide aquí: se usa la que el job `gsc` dejó en
`gsc_site_sync.connection_id`. Sin esa cuenta (o si está para reconectar) la
propiedad se apunta como `pending_access`/`no_access` y se sigue.

Dos avisos para quien lea estas tablas:
- Google anonimiza las consultas poco frecuentes: la suma de consultas de un
  día es menor que el total de `gsc_daily`. "Sin clasificar" = total − suma.
- Las impresiones por página no suman el total de la propiedad (una búsqueda
  que enseña dos páginas cuenta en las dos).

Reglas de las cifras (globales): clics e impresiones se suman en la ventana;
la posición es la media ponderada por impresiones.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.models import GscConnection, GscDetailSync, GscPageDaily, GscQueryDaily, GscSiteSync
from backend.services import gsc_service
from backend.services.gsc_service import GscAuthError, GscSiteError, TAIL_DAYS
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

# Días de detalle que se guardan (y que se piden la primera vez).
DETAIL_DAYS = 120
# La primera importación va en tramos para no pedir 120 días de golpe.
CHUNK_DAYS = 14
# Máximo de filas por petición que admite la API.
PAGE_SIZE = 25000
INSERT_BATCH = 5000
MAX_PAGE_LENGTH = 2000
PAGE_PAUSE_SECONDS = 0.2
DIMENSIONS = ("query", "page")
_MODELS = {"query": GscQueryDaily, "page": GscPageDaily}

_sleep = time.sleep


@dataclass(frozen=True)
class DetailRow:
    date: date
    key: str
    clicks: int
    impressions: int
    position: float


# ── API de Search Console ────────────────────────────────────────────


def _merge(rows: list[DetailRow]) -> list[DetailRow]:
    """Une filas con la misma clave (p. ej. dos URLs que coinciden en sus 2.000
    primeros caracteres): suma clics/impresiones y pondera la posición."""
    merged: dict[tuple[date, str], list[float]] = {}
    for r in rows:
        acc = merged.setdefault((r.date, r.key), [0, 0, 0.0, 0.0, 0])
        acc[0] += r.clicks
        acc[1] += r.impressions
        acc[2] += r.position * r.impressions
        acc[3] += r.position
        acc[4] += 1
    if len(merged) == len(rows):
        return rows
    return [
        DetailRow(day, key, int(clicks), int(impressions),
                  float(weighted / impressions if impressions else plain / n))
        for (day, key), (clicks, impressions, weighted, plain, n) in merged.items()
    ]


def _query_dim_sync(encrypted_refresh_token: str, site_url: str, start: date, end: date,
                    dimension: str) -> list[DetailRow]:
    """Todas las filas (día, consulta|página) del tramo, paginando de 25.000 en 25.000."""
    rows: list[DetailRow] = []
    start_row = 0
    try:
        service = gsc_service._service(encrypted_refresh_token)
        while True:
            body = {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["date", dimension],
                "type": "web",
                "dataState": "final",
                "rowLimit": PAGE_SIZE,
                "startRow": start_row,
            }
            result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
            page = result.get("rows", [])
            for row in page:
                key = row["keys"][1]
                if dimension == "page":
                    key = key[:MAX_PAGE_LENGTH]
                rows.append(DetailRow(
                    date=date.fromisoformat(row["keys"][0]),
                    key=key,
                    clicks=int(row.get("clicks", 0)),
                    impressions=int(row.get("impressions", 0)),
                    position=float(row.get("position", 0.0)),
                ))
            if len(page) < PAGE_SIZE:
                break
            start_row += PAGE_SIZE
            _sleep(PAGE_PAUSE_SECONDS)
    except (GscAuthError, GscSiteError):
        raise
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise gsc_service._translate(exc) from exc
    return _merge(rows)


async def query_dimension(encrypted_refresh_token: str, site_url: str, start: date, end: date,
                          dimension: str) -> list[DetailRow]:
    return await asyncio.to_thread(_query_dim_sync, encrypted_refresh_token, site_url, start, end, dimension)


# ── Importación ──────────────────────────────────────────────────────


def plan_chunks(*, backfilled: bool, last_data_date: date | None, today: date) -> tuple[list[tuple[date, date]], bool]:
    """Tramos a pedir y si es la primera importación.

    Primera vez: los últimos 120 días, en tramos de 14. Después: los últimos
    7 días desde el último con datos (GSC los revisa), igual que `gsc`.
    """
    end = today - timedelta(days=1)
    floor = end - timedelta(days=DETAIL_DAYS - 1)
    if not backfilled:
        start = floor
    else:
        anchor = last_data_date or end
        start = max(min(anchor, end) - timedelta(days=TAIL_DAYS), floor)
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks, not backfilled


async def _replace(db, dimension: str, site_url: str, start: date, end: date, rows: list[DetailRow]) -> None:
    """Sustituye el tramo entero en una transacción corta: borra y vuelve a insertar.

    Reemplazar (no upsert) quita también las consultas/páginas que ya no salen.
    """
    model = _MODELS[dimension]
    key_column = dimension
    await db.execute(delete(model).where(
        model.site_url == site_url, model.date >= start, model.date <= end,
    ))
    for i in range(0, len(rows), INSERT_BATCH):
        batch = rows[i:i + INSERT_BATCH]
        await db.execute(pg_insert(model).values([
            {"site_url": site_url, "date": r.date, key_column: r.key, "clicks": r.clicks,
             "impressions": r.impressions, "position": r.position}
            for r in batch
        ]))
    await db.commit()


def _retention_cutoff(last_data_date: date | None, today: date) -> date:
    """Último día que se borra: 120 días antes del último con datos.

    Si la propiedad deja de actualizarse, la ventana sigue avanzando con el
    calendario (con el margen de los 7 días de cola), para que nada viva más
    de lo que dice la política de privacidad.
    """
    end = today - timedelta(days=1)
    anchor = max(last_data_date or end, end - timedelta(days=TAIL_DAYS))
    return anchor - timedelta(days=DETAIL_DAYS)


async def _prune_site(db, site_url: str, cutoff: date) -> None:
    for model in _MODELS.values():
        await db.execute(delete(model).where(model.site_url == site_url, model.date <= cutoff))


async def _row_counts(db, site_url: str) -> tuple[int, int]:
    counts = []
    for model in (GscQueryDaily, GscPageDaily):
        counts.append(int(await db.scalar(
            select(func.count()).select_from(model).where(model.site_url == site_url)
        ) or 0))
    return counts[0], counts[1]


async def _record_state(db, site_url: str, *, error_code: str | None, backfilled: bool = False,
                        last_data_date: date | None = None, counts: tuple[int, int] | None = None) -> None:
    state = await db.get(GscDetailSync, site_url)
    if state is None:
        state = GscDetailSync(site_url=site_url)
        db.add(state)
    now = datetime.now(UTC)
    state.last_synced_at = now
    state.error_code = error_code
    if backfilled:
        state.backfilled_at = now
    if last_data_date and (state.last_data_date is None or last_data_date > state.last_data_date):
        state.last_data_date = last_data_date
    if counts is not None:
        state.query_rows, state.page_rows = counts
    await db.commit()


async def sync_site_detail(db, encrypted_refresh_token: str, site_url: str, *, fetch=query_dimension,
                           today: date | None = None) -> dict:
    """Importa el detalle de una propiedad. Devuelve las filas guardadas por dimensión.

    Por tramo y dimensión: llamada a Google SIN transacción abierta y después
    una transacción corta que borra el tramo y lo vuelve a insertar.
    """
    today = today or business_today()
    state = await db.get(GscDetailSync, site_url)
    chunks, backfill = plan_chunks(
        backfilled=bool(state and state.backfilled_at),
        last_data_date=state.last_data_date if state else None,
        today=today,
    )
    await db.commit()

    last_data: date | None = None
    written = {d: 0 for d in DIMENSIONS}
    try:
        for start, end in chunks:
            for dimension in DIMENSIONS:
                rows = await fetch(encrypted_refresh_token, site_url, start, end, dimension)
                await _replace(db, dimension, site_url, start, end, rows)
                written[dimension] += len(rows)
                newest = max((r.date for r in rows), default=None)
                if newest and (last_data is None or newest > last_data):
                    last_data = newest
    except GscSiteError as exc:
        await _record_state(db, site_url, error_code=exc.code, last_data_date=last_data)
        raise

    known = max(filter(None, [last_data, state.last_data_date if state else None]), default=None)
    await _prune_site(db, site_url, _retention_cutoff(known, today))
    counts = await _row_counts(db, site_url)
    await _record_state(db, site_url, error_code=None, backfilled=backfill,
                        last_data_date=last_data, counts=counts)
    return written


async def prune(db, *, today: date | None = None) -> None:
    """Retención: fuera lo de más de 120 días y todo lo de webs que ya no sigue
    ningún cliente activo (cliente Antiguo o propiedad cambiada).

    `delete()` masivos: no pasan por el ORM ni entran en el Deshacer, a propósito.
    """
    today = today or business_today()
    tracked = set(await gsc_service.tracked_sites(db))
    stored: set[str] = set()
    for model in (GscQueryDaily, GscPageDaily, GscDetailSync):
        stored |= set((await db.scalars(select(model.site_url).distinct())).all())
    untracked = sorted(stored - tracked)
    if untracked:
        for model in (GscQueryDaily, GscPageDaily, GscDetailSync):
            await db.execute(delete(model).where(model.site_url.in_(untracked)))
    states = {s.site_url: s.last_data_date for s in (await db.scalars(
        select(GscDetailSync).where(GscDetailSync.site_url.in_(sorted(stored & tracked)))
    )).all()} if stored & tracked else {}
    for site in sorted(stored & tracked):
        await _prune_site(db, site, _retention_cutoff(states.get(site), today))
    await db.commit()


async def sync_all_detail(session_factory, *, fetch=query_dimension, today: date | None = None) -> dict:
    """Una pasada sobre todas las propiedades de clientes activos, con la cuenta
    que el job `gsc` les asignó. Cada propiedad en su sesión; un fallo no para
    a las demás. La retención se aplica siempre, haya cuenta o no."""
    async with session_factory() as db:
        await prune(db, today=today)
        any_connected = await db.scalar(select(GscConnection.id).where(GscConnection.status == "connected").limit(1))
        if any_connected is None:
            has_any = await db.scalar(select(GscConnection.id).limit(1))
            return {"status": "reconnect_required" if has_any else "not_connected",
                    "synced": 0, "failed": 0, "skipped": 0}
        sites = await gsc_service.tracked_sites(db)
        tokens = {c.id: c.refresh_token for c in (await db.scalars(
            select(GscConnection).where(GscConnection.status == "connected")
        )).all()}
        site_states = {s.site_url: (s.connection_id, s.error_code) for s in (await db.scalars(
            select(GscSiteSync).where(GscSiteSync.site_url.in_(sites))
        )).all()} if sites else {}

    synced = failed = skipped = 0
    broken: list[int] = []
    for site in sites:
        connection_id, gsc_error = site_states.get(site, (None, None))
        if connection_id is None or connection_id not in tokens:
            # El job `gsc` decide la cuenta; mientras no haya una válida, se apunta y se sigue.
            code = "no_access" if gsc_error == "no_access" else "pending_access"
            async with session_factory() as db:
                await _record_state(db, site, error_code=code)
            skipped += 1
            continue
        try:
            async with session_factory() as db:
                await sync_site_detail(db, tokens[connection_id], site, fetch=fetch, today=today)
            synced += 1
        except GscAuthError:
            await gsc_service._mark_reconnect(session_factory, connection_id)
            tokens.pop(connection_id, None)
            broken.append(connection_id)
            async with session_factory() as db:
                await _record_state(db, site, error_code="reconnect_required")
            failed += 1
        except GscSiteError as exc:
            failed += 1
            logger.warning("Search Console (detalle): fallo al importar %s (%s)", site, exc.code)
    status = "reconnect_required" if broken else "ok"
    return {"status": status, "synced": synced, "failed": failed, "skipped": skipped}
