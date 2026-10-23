"""Leads por landing de GA4 (heredado de The Engine, 22 oct 2026).

Con las mismas cuentas y en la misma pasada que `ga4_service`, se piden a la
Data API los eventos que el cliente cuenta como lead
(`clients.ga4_lead_events`, por defecto ``["generate_lead"]``; admite nombres
exactos y prefijos terminados en ``*``, como ``generate_lead_*``) por día,
landing y canal, y se guardan en `ga4_lead_daily`:

- ``landing_page`` = host + ruta de la primera página de la sesión, sin
  parámetros de seguimiento (utm_*, gclid, fbclid…), recortada a 2.000
  caracteres. El host va delante porque en Engine las landings de pago de un
  subdominio se mezclaban con las de la web principal (Bug E-1).
- ``channel`` = `sessionDefaultChannelGroup` (Organic Search, Paid Search…).
- ``leads`` = número de eventos. Nada por usuario.

Retención: 16 meses contando el actual (el mismo límite que el historial de
Search Console), y fuera todo lo de propiedades que ya no tiene ningún cliente
activo. Si cambian los eventos que cuentan, se vuelve a importar todo.

Como el resto de cifras de Google, esto NO va a ningún camino de IA (lo vigila
`test_el_detalle_de_search_console_no_llega_a_la_ia`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.bulk import insert_chunks
from backend.db.models import Client, ClientStatus, Ga4LeadDaily, Ga4PropertySync
from backend.services.gsc_detail_service import history_floor
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

DEFAULT_EVENTS = ("generate_lead",)
MAX_EVENTS = 20
MAX_LANDING_LENGTH = 2000
MAX_CHANNEL_LENGTH = 64
# Igual que `ga4_service`: 16 meses la primera vez y luego la última semana.
BACKFILL_DAYS = 486
TAIL_DAYS = 7
PAGE_SIZE = 100000
WINDOW_CHOICES = (7, 28)
TOP_LANDINGS = 10

# Nombre de evento de GA4 (letra + letras/dígitos/_ hasta 40) y, opcional, "*" final = prefijo.
_EVENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\*?")

# Parámetros de seguimiento que parten una misma landing en varias filas
# (los de Engine más los habituales de Google y analítica).
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "gclsrc", "msclkid", "dclid", "wbraid", "gbraid", "twclid", "ttclid",
    "li_fat_id", "mc_cid", "mc_eid", "ltk_fcm", "ltk_fag", "ltk_fac", "gc_id", "h_ga_id", "h_ad_id",
    "srsltid", "_gl", "_ga", "igshid", "yclid",
})


# ── Configuración por cliente ────────────────────────────────────────


def clean_lead_events(values) -> list[str]:
    """Valida la lista de eventos que cuentan como lead. Quita duplicados y espacios."""
    if values is None:
        return list(DEFAULT_EVENTS)
    if not isinstance(values, list):
        raise ValueError("Los eventos de lead son una lista")
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Cada evento de lead es un texto")
        name = value.strip()
        if not name:
            continue
        if not _EVENT_RE.fullmatch(name):
            raise ValueError(
                f"«{name}» no es un evento de GA4 válido: letras, números y guiones bajos (hasta 40), "
                "empezando por letra; termina en * para contar todos los que empiezan así"
            )
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("Indica al menos un evento que cuente como lead")
    if len(out) > MAX_EVENTS:
        raise ValueError(f"Como mucho {MAX_EVENTS} eventos de lead")
    return out


class EventMatcher:
    """¿Cuenta este evento como lead? Nombre exacto o prefijo (``generate_lead_*``)."""

    def __init__(self, patterns):
        self.exact = {p for p in patterns if not p.endswith("*")}
        self.prefixes = tuple(p[:-1] for p in patterns if p.endswith("*"))

    def __call__(self, name: str | None) -> bool:
        name = name or ""
        return name in self.exact or (bool(self.prefixes) and name.startswith(self.prefixes))


def events_key(patterns) -> str:
    """Forma canónica de un conjunto de eventos (para saber si ha cambiado)."""
    return json.dumps(sorted(set(patterns)), separators=(",", ":"))


async def property_lead_events(db) -> dict[str, list[str]]:
    """Eventos de lead por propiedad de GA4 de los clientes activos. Si dos
    clientes comparten propiedad, cuentan los de los dos."""
    from backend.services.ga4_service import normalize_property

    rows = (await db.execute(
        select(Client.ga4_property_id, Client.ga4_lead_events)
        .where(Client.status == ClientStatus.active, Client.ga4_property_id.isnot(None))
    )).all()
    out: dict[str, set[str]] = {}
    for prop, events in rows:
        pid = normalize_property(prop)
        if pid:
            out.setdefault(pid, set()).update(events or DEFAULT_EVENTS)
    return {pid: sorted(events) for pid, events in out.items()}


# ── Normalización de landing y canal (la misma para GA4 y para lo de Engine) ──


def strip_tracking(query: str) -> str:
    """Quita los parámetros de seguimiento y respeta el orden de los demás."""
    if not query:
        return ""
    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    return urlencode(kept, doseq=True)


def clean_landing(landing: str | None, host: str | None = None) -> str:
    """'/cpe/?utm_source=x&a=1' + 'go.fit.es' → 'go.fit.es/cpe/?a=1'.

    GA4 a veces devuelve la URL entera: el host sale de ahí si no viene aparte.
    Sin ruta = '/'. '(not set)' se deja tal cual (Google no sabe la landing).
    """
    landing = (landing or "").strip()
    host = (host or "").strip().lower()
    if host in ("(not set)", "(none)"):
        host = ""
    if landing in ("(not set)", "(none)"):
        return landing
    if landing.startswith(("http://", "https://")):
        parts = urlsplit(landing)
        host = host or (parts.hostname or "").lower()
        path, query = parts.path, parts.query
    else:
        path, _, query = landing.partition("?")
        path = path.split("#", 1)[0]
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    query = strip_tracking(query)
    out = f"{host}{path}" + (f"?{query}" if query else "")
    return out[:MAX_LANDING_LENGTH]


def clean_channel(channel: str | None) -> str:
    channel = (channel or "").strip()
    if not channel or channel.lower() == "unknown":
        return "(not set)"
    return channel[:MAX_CHANNEL_LENGTH]


@dataclass(frozen=True)
class LeadRow:
    date: date
    landing_page: str
    channel: str
    leads: int


def merge_rows(rows) -> list[LeadRow]:
    """Suma las filas que acaban en la misma (día, landing, canal): p. ej. dos
    URLs que sólo se diferencian en el fbclid."""
    acc: dict[tuple[date, str, str], int] = {}
    for r in rows:
        key = (r.date, r.landing_page, r.channel)
        acc[key] = acc.get(key, 0) + int(r.leads)
    return [LeadRow(d, landing, channel, leads) for (d, landing, channel), leads in sorted(acc.items())
            if leads > 0]


# ── API de Google ────────────────────────────────────────────────────


def _event_filter(patterns) -> dict:
    filters = [
        {"filter": {"fieldName": "eventName", "stringFilter": (
            {"matchType": "BEGINS_WITH", "value": p[:-1], "caseSensitive": True} if p.endswith("*")
            else {"matchType": "EXACT", "value": p, "caseSensitive": True})}}
        for p in patterns
    ]
    return filters[0] if len(filters) == 1 else {"orGroup": {"expressions": filters}}


def report_body(patterns, start: date, end: date, offset: int = 0) -> dict:
    return {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [{"name": "date"}, {"name": "landingPagePlusQueryString"}, {"name": "hostName"},
                       {"name": "sessionDefaultChannelGroup"}, {"name": "eventName"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": _event_filter(patterns),
        "limit": PAGE_SIZE,
        "offset": offset,
    }


def aggregate_report_rows(rows: list[dict], matcher: EventMatcher) -> list[LeadRow]:
    """Filas de la Data API → (día, landing limpia, canal) con sus leads."""
    out = []
    for row in rows:
        dims = [d.get("value") for d in row.get("dimensionValues", [])]
        if not matcher(dims[4]):
            continue
        count = int(float((row.get("metricValues") or [{}])[0].get("value") or 0))
        out.append(LeadRow(datetime.strptime(dims[0], "%Y%m%d").date(), clean_landing(dims[1], dims[2]),
                           clean_channel(dims[3]), count))
    return merge_rows(out)


def _query_leads_sync(encrypted_refresh_token: str, property_id: str, start: date, end: date,
                      patterns: list[str]) -> list[LeadRow]:
    from googleapiclient.discovery import build

    from backend.services.ga4_service import _credentials, _translate

    rows: list[dict] = []
    try:
        data = build("analyticsdata", "v1beta", credentials=_credentials(encrypted_refresh_token),
                     cache_discovery=False)
        offset = 0
        while True:
            result = data.properties().runReport(
                property=f"properties/{property_id}", body=report_body(patterns, start, end, offset),
            ).execute()
            page = result.get("rows", [])
            rows.extend(page)
            offset += len(page)
            if not page or offset >= int(result.get("rowCount") or 0):
                break
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise _translate(exc) from exc
    return aggregate_report_rows(rows, EventMatcher(patterns))


async def query_leads(encrypted_refresh_token: str, property_id: str, start: date, end: date,
                      patterns: list[str]) -> list[LeadRow]:
    return await asyncio.to_thread(_query_leads_sync, encrypted_refresh_token, property_id, start, end, patterns)


# ── Importación ──────────────────────────────────────────────────────


def retention_floor(today: date) -> date:
    """Primer día que se guarda: el día 1 del mes de hace 15 meses (16 contando el actual)."""
    return history_floor(today)


async def replace_range(db, property_id: str, start: date, end: date, rows: list[LeadRow]) -> int:
    """Sustituye los días [start, end] de la propiedad (borra e inserta). No hace commit."""
    await db.execute(delete(Ga4LeadDaily).where(
        Ga4LeadDaily.property_id == property_id, Ga4LeadDaily.date >= start, Ga4LeadDaily.date <= end,
    ))
    values = [{"property_id": property_id, "date": r.date, "landing_page": r.landing_page,
               "channel": r.channel, "leads": r.leads} for r in rows if start <= r.date <= end]
    for batch in insert_chunks(Ga4LeadDaily, values):
        await db.execute(pg_insert(Ga4LeadDaily).values(batch))
    return len(values)


async def sync_property_leads(db, token: str, property_id: str, events: list[str], *, fetch=None,
                              today: date | None = None) -> int:
    """Importa los leads de una propiedad. Primera vez (o eventos cambiados):
    16 meses; después, la última semana. Llamada a Google sin transacción
    abierta y luego una transacción corta que sustituye el tramo."""
    fetch = fetch or query_leads
    today = today or business_today()
    end = today - timedelta(days=1)
    floor = retention_floor(today)
    key = events_key(events)
    state = await db.get(Ga4PropertySync, property_id)
    full = state is None or state.leads_backfilled_at is None or state.leads_events != key
    if full:
        start = max(end - timedelta(days=BACKFILL_DAYS), floor)
    else:
        start = max((state.leads_synced_through or end) - timedelta(days=TAIL_DAYS), floor)
    await db.commit()

    from backend.services.ga4_service import Ga4Error

    try:
        rows = await fetch(token, property_id, start, end, list(events))
    except Ga4Error as exc:
        await _record(db, property_id, error_code=exc.code)
        raise
    written = await replace_range(db, property_id, start, end, rows)
    await _record(db, property_id, error_code=None, synced_through=end, events_key_=key,
                  covered_from=start if full else None, backfilled=full)
    return written


async def _record(db, property_id: str, *, error_code: str | None, synced_through: date | None = None,
                  events_key_: str | None = None, covered_from: date | None = None,
                  backfilled: bool = False) -> None:
    state = await db.get(Ga4PropertySync, property_id)
    if state is None:
        state = Ga4PropertySync(property_id=property_id)
        db.add(state)
    state.leads_error_code = error_code
    if synced_through is not None:
        state.leads_synced_through = synced_through
    if events_key_ is not None:
        state.leads_events = events_key_
    if backfilled:
        state.leads_backfilled_at = datetime.now(UTC)
        state.leads_covered_from = covered_from
    await db.commit()


async def prune(db, *, today: date | None = None) -> None:
    """Retención: fuera lo anterior a los 16 meses y todo lo de propiedades que
    ya no tiene ningún cliente activo (su estado de leads vuelve a cero, para
    que si vuelve se importe desde el principio).

    `delete()` masivos: no pasan por el ORM ni entran en el Deshacer, a propósito.
    """
    today = today or business_today()
    tracked = set(await property_lead_events(db))
    stored = set((await db.scalars(select(Ga4LeadDaily.property_id).distinct())).all())
    untracked = sorted(stored - tracked)
    if untracked:
        await db.execute(delete(Ga4LeadDaily).where(Ga4LeadDaily.property_id.in_(untracked)))
    stale_state = select(Ga4PropertySync.property_id).where(Ga4PropertySync.leads_events.isnot(None))
    if tracked:
        stale_state = stale_state.where(Ga4PropertySync.property_id.not_in(sorted(tracked)))
    await db.execute(update(Ga4PropertySync).where(Ga4PropertySync.property_id.in_(stale_state)).values(
        leads_backfilled_at=None, leads_events=None, leads_synced_through=None, leads_covered_from=None,
        leads_error_code=None,
    ))
    await db.execute(delete(Ga4LeadDaily).where(Ga4LeadDaily.date < retention_floor(today)))
    await db.commit()


# ── Lectura: ficha del cliente ───────────────────────────────────────


def _pct(current: int, previous: int | None) -> float | None:
    if previous is None or not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


async def _grouped(db, pid: str, column, start: date, end: date) -> dict[str, int]:
    rows = (await db.execute(
        select(column, func.sum(Ga4LeadDaily.leads))
        .where(Ga4LeadDaily.property_id == pid, Ga4LeadDaily.date >= start, Ga4LeadDaily.date <= end)
        .group_by(column)
    )).all()
    return {key: int(total) for key, total in rows}


async def client_leads(db, client: Client, *, days: int = 28) -> dict:
    """Leads de los últimos ``days`` días importados frente a los ``days``
    anteriores: total, landings con más leads y reparto por canal."""
    from backend.services.ga4_service import normalize_property

    events = list(client.ga4_lead_events or DEFAULT_EVENTS)
    pid = normalize_property(client.ga4_property_id)
    if pid is None:
        return {"status": "no_property", "events": events, "days": days}
    state = await db.get(Ga4PropertySync, pid)
    if state is None or state.leads_synced_through is None:
        imported = await db.scalar(select(func.max(Ga4LeadDaily.date)).where(Ga4LeadDaily.property_id == pid))
        if imported is None:
            return {"status": "not_synced", "property_id": pid, "events": events, "days": days,
                    "error_code": state.leads_error_code if state else None}
        end = imported
    else:
        end = state.leads_synced_through
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    # Lo anterior al primer día con datos (de The Agency o importado de Engine) no es un cero.
    first_day = await db.scalar(select(func.min(Ga4LeadDaily.date)).where(Ga4LeadDaily.property_id == pid))
    earliest = min(filter(None, [first_day, state.leads_covered_from if state else None]), default=None)
    comparable = earliest is not None and earliest <= prev_start

    landings = await _grouped(db, pid, Ga4LeadDaily.landing_page, start, end)
    channels = await _grouped(db, pid, Ga4LeadDaily.channel, start, end)
    prev_landings = await _grouped(db, pid, Ga4LeadDaily.landing_page, prev_start, prev_end) if comparable else {}
    prev_channels = await _grouped(db, pid, Ga4LeadDaily.channel, prev_start, prev_end) if comparable else {}

    def item(name_key: str, name: str, current: dict, previous: dict) -> dict:
        prev = previous.get(name, 0) if comparable else None
        return {name_key: name, "leads": current.get(name, 0), "previous": prev,
                "change_pct": _pct(current.get(name, 0), prev)}

    total = sum(landings.values())
    prev_total = sum(prev_landings.values()) if comparable else None
    top = sorted(landings, key=lambda k: (-landings[k], k))[:TOP_LANDINGS]
    return {
        "status": "ok", "property_id": pid, "events": events, "days": days,
        "start": start.isoformat(), "end": end.isoformat(),
        "previous_start": prev_start.isoformat(), "previous_end": prev_end.isoformat(),
        "comparable": comparable,
        "error_code": state.leads_error_code if state else None,
        "total": {"leads": total, "previous": prev_total, "change_pct": _pct(total, prev_total)},
        "landings": [item("landing_page", k, landings, prev_landings) for k in top],
        "landing_count": len(landings),
        "channels": [item("channel", k, channels, prev_channels)
                     for k in sorted(set(channels) | set(prev_channels),
                                     key=lambda k: (-channels.get(k, 0), -prev_channels.get(k, 0), k))],
    }
