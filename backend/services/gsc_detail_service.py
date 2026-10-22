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

Historial mensual (`gsc_query_monthly`, hasta 16 meses): tras cada pasada se
resume cada mes COMPLETO del detalle diario en un total por consulta (los
120 días no llegan a 16 meses). Los meses anteriores a esos 120 días se piden
una sola vez a Google, un mes por petición (marca `monthly_backfilled_at`).

Historial importado de The Engine (`source='engine'`,
`scripts/import_engine_positions.py`): sólo meses anteriores al primero que
tiene The Agency; no caduca a los 16 meses, pero se borra con la web (poda de
webs sin cliente activo y purga al desconectar).

Reglas de las cifras (globales): clics e impresiones se suman en la ventana;
la posición es la media ponderada por impresiones.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.models import (
    GscConnection, GscDetailSync, GscPageDaily, GscQueryDaily, GscQueryMonthly, GscSiteSync,
)
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

# Historial mensual por consulta: 16 meses contando el actual (lo que guarda
# Google). El mes actual nunca está completo, así que como mucho hay 15 cerrados.
HISTORY_MONTHS = 16

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


@dataclass(frozen=True)
class MonthRow:
    query: str
    clicks: int
    impressions: int
    position: float


def _query_month_sync(encrypted_refresh_token: str, site_url: str, start: date, end: date) -> list[MonthRow]:
    """Totales por consulta de un mes entero (dimensión `query`, sin día): una
    petición por mes, paginando de 25.000 en 25.000."""
    rows: list[MonthRow] = []
    start_row = 0
    try:
        service = gsc_service._service(encrypted_refresh_token)
        while True:
            body = {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["query"],
                "type": "web",
                "dataState": "final",
                "rowLimit": PAGE_SIZE,
                "startRow": start_row,
            }
            result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
            page = result.get("rows", [])
            for row in page:
                rows.append(MonthRow(
                    query=row["keys"][0],
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
    return rows


async def query_month(encrypted_refresh_token: str, site_url: str, start: date, end: date) -> list[MonthRow]:
    return await asyncio.to_thread(_query_month_sync, encrypted_refresh_token, site_url, start, end)


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
                           fetch_month=None, today: date | None = None) -> dict:
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
    await sync_monthly(db, encrypted_refresh_token, site_url, fetch_month=fetch_month, today=today)
    return written


# ── Historial mensual por consulta ───────────────────────────────────


def add_months(month: date, n: int) -> date:
    """Día 1 del mes que está `n` meses después (o antes) del de `month`."""
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def month_end(month: date) -> date:
    return add_months(month, 1) - timedelta(days=1)


def history_floor(today: date) -> date:
    """Primer mes que se guarda: 16 meses contando el actual (22 oct 2026 →
    jul 2025). Lo anterior se borra: es el límite que promete la política."""
    return add_months(today.replace(day=1), -(HISTORY_MONTHS - 1))


def coverage_start(first_day: date | None, last_data_date: date | None, today: date) -> date | None:
    """Primer día desde el que el detalle diario está entero hasta `last_data_date`.

    El más tardío entre el primer día guardado de consultas y el siguiente al
    último que borra la retención. Un mes cuenta como completo sólo si todos
    sus días caen desde aquí. Si el primer día guardado es posterior al real
    (días sin ninguna consulta), ese mes se pide a Google entero: sale bien
    por el lado seguro.
    """
    if last_data_date is None:
        return None
    floor = _retention_cutoff(last_data_date, today) + timedelta(days=1)
    return max(first_day, floor) if first_day is not None else floor


def complete_months(coverage: date | None, last_data_date: date | None) -> list[date]:
    """Meses que el detalle diario tiene ENTEROS: todos sus días desde
    `coverage` y con datos finales hasta su último día."""
    if coverage is None or last_data_date is None:
        return []
    month = coverage if coverage.day == 1 else add_months(coverage, 1)
    out = []
    while month_end(month) <= last_data_date:
        out.append(month)
        month = add_months(month, 1)
    return out


def backfill_months(coverage: date | None, last_data_date: date | None, today: date) -> list[date]:
    """Meses del historial que el detalle diario NO tiene enteros (empiezan
    antes de `coverage`): se piden a Google una vez, un mes por petición."""
    if coverage is None or last_data_date is None:
        return []
    out = []
    month = history_floor(today)
    while month < coverage and month_end(month) <= last_data_date:
        out.append(month)
        month = add_months(month, 1)
    return out


def month_values(month: date, site_url: str, rows: list[MonthRow]) -> list[dict]:
    """Filas a guardar de un mes pedido a Google. Su posición ya es la media
    ponderada del mes, así que SUM(posición × impresiones) = posición ×
    impresiones. Una consulta repetida se suma."""
    merged: dict[str, list[float]] = {}
    for r in rows:
        acc = merged.setdefault(r.query, [0, 0, 0.0])
        acc[0] += r.clicks
        acc[1] += r.impressions
        acc[2] += r.position * r.impressions
    return [
        {"site_url": site_url, "month": month, "query": query, "clicks": int(clicks),
         "impressions": int(impressions), "weighted_position_sum": float(weighted)}
        for query, (clicks, impressions, weighted) in merged.items()
    ]


async def _replace_month(db, site_url: str, month: date, rows: list[MonthRow]) -> None:
    await db.execute(delete(GscQueryMonthly).where(
        GscQueryMonthly.site_url == site_url, GscQueryMonthly.month == month,
    ))
    values = month_values(month, site_url, rows)
    for i in range(0, len(values), INSERT_BATCH):
        await db.execute(pg_insert(GscQueryMonthly).values(values[i:i + INSERT_BATCH]))
    await db.commit()


_ROLLUP_SQL = text("""
    INSERT INTO gsc_query_monthly (site_url, month, query, clicks, impressions, weighted_position_sum)
    SELECT site_url, CAST(date_trunc('month', CAST(date AS timestamp)) AS date), query,
           SUM(clicks), SUM(impressions), SUM(CAST(position AS double precision) * impressions)
    FROM gsc_query_daily
    WHERE site_url = :site AND date >= :start AND date <= :end
    GROUP BY site_url, CAST(date_trunc('month', CAST(date AS timestamp)) AS date), query
""")


async def rollup_months(db, site_url: str, months: list[date]) -> None:
    """Resume en `gsc_query_monthly` los meses completos del detalle diario.

    Reemplaza cada mes entero (borra e inserta): repetirlo da lo mismo y
    recoge las revisiones de Google de los últimos días. Los meses son seguidos.
    """
    if not months:
        return
    start, end = months[0], month_end(months[-1])
    await db.execute(delete(GscQueryMonthly).where(
        GscQueryMonthly.site_url == site_url,
        GscQueryMonthly.month >= start, GscQueryMonthly.month <= months[-1],
    ))
    await db.execute(_ROLLUP_SQL, {"site": site_url, "start": start, "end": end})
    await db.commit()


async def sync_monthly(db, encrypted_refresh_token: str, site_url: str, *, fetch_month=None,
                       today: date | None = None) -> None:
    """Historial mensual de una propiedad, justo después de importar su detalle diario.

    1. Si falta la importación inicial (`monthly_backfilled_at` NULL), pide a
       Google cada mes del historial que el detalle diario no tiene entero.
       Un fallo de la propiedad se apunta en el log y se reintenta en la
       próxima pasada sin bloquear el Control SEO; los de cuenta sí suben.
    2. Resume los meses completos del detalle diario.
    """
    today = today or business_today()
    # Se resuelve aquí (no en la firma) para que los tests puedan sustituirla en el módulo.
    fetch_month = fetch_month or query_month
    state = await db.get(GscDetailSync, site_url)
    if state is None or state.backfilled_at is None or state.last_data_date is None:
        return
    first_day = await db.scalar(select(func.min(GscQueryDaily.date)).where(GscQueryDaily.site_url == site_url))
    coverage = coverage_start(first_day, state.last_data_date, today)
    last_data_date = state.last_data_date
    pending = state.monthly_backfilled_at is None
    await db.commit()

    if pending:
        try:
            for month in backfill_months(coverage, last_data_date, today):
                # Llamada a Google sin transacción abierta; luego reemplazo del mes.
                rows = await fetch_month(encrypted_refresh_token, site_url, month, month_end(month))
                await _replace_month(db, site_url, month, rows)
        except GscSiteError as exc:
            await db.rollback()
            logger.warning("Search Console (historial mensual): fallo al importar %s (%s)", site_url, exc.code)
        else:
            state = await db.get(GscDetailSync, site_url)
            if state is not None:
                state.monthly_backfilled_at = datetime.now(UTC)
                await db.commit()

    await rollup_months(db, site_url, complete_months(coverage, last_data_date))


async def prune(db, *, today: date | None = None) -> None:
    """Retención: fuera el detalle diario de más de 120 días, el historial
    mensual anterior a los 16 meses (salvo el importado de The Engine) y todo
    lo de webs que ya no sigue ningún cliente activo (cliente Antiguo o
    propiedad cambiada), importado incluido.

    `delete()` masivos: no pasan por el ORM ni entran en el Deshacer, a propósito.
    """
    today = today or business_today()
    tracked = set(await gsc_service.tracked_sites(db))
    stored: set[str] = set()
    for model in (GscQueryDaily, GscPageDaily, GscQueryMonthly, GscDetailSync):
        stored |= set((await db.scalars(select(model.site_url).distinct())).all())
    untracked = sorted(stored - tracked)
    if untracked:
        for model in (GscQueryDaily, GscPageDaily, GscQueryMonthly, GscDetailSync):
            await db.execute(delete(model).where(model.site_url.in_(untracked)))
    # Lo importado de The Engine (`source='engine'`) no caduca a los 16 meses:
    # se queda mientras la web tenga cliente activo (lo de arriba lo borra si no).
    await db.execute(delete(GscQueryMonthly).where(
        GscQueryMonthly.month < history_floor(today), GscQueryMonthly.source == "google",
    ))
    states = {s.site_url: s.last_data_date for s in (await db.scalars(
        select(GscDetailSync).where(GscDetailSync.site_url.in_(sorted(stored & tracked)))
    )).all()} if stored & tracked else {}
    for site in sorted(stored & tracked):
        await _prune_site(db, site, _retention_cutoff(states.get(site), today))
    await db.commit()


async def sync_all_detail(session_factory, *, fetch=query_dimension, fetch_month=None,
                          today: date | None = None) -> dict:
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
                await sync_site_detail(db, tokens[connection_id], site, fetch=fetch, fetch_month=fetch_month,
                                       today=today)
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
