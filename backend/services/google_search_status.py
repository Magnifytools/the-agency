"""Actualizaciones e incidencias de Google Search, del panel oficial de estado.

Google publica en https://status.search.google.com/ las actualizaciones del
algoritmo (core, spam…) y las incidencias de rastreo, indexación y servicio,
con su inicio y su final. Se leen en vivo (caché en proceso de 6 h) para
pintarlas como anotaciones en las gráficas SEO: no se guardan en la BD.

Un fallo de red no rompe nada: se devuelve lo último que se tuvo (o nada) y
la respuesta lo dice con `available: False`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

INCIDENTS_URL = "https://status.search.google.com/incidents.json"
CACHE_SECONDS = 6 * 3600
TIMEOUT_SECONDS = 10

# Nombre del servicio en el panel → cómo lo llamamos.
SERVICE_LABELS = {
    "Ranking": "Actualización de Google",
    "Crawling": "Incidencia de rastreo de Google",
    "Indexing": "Incidencia de indexación de Google",
    "Serving": "Incidencia de Google",
}


@dataclass(frozen=True)
class GoogleEvent:
    start: date
    end: date | None
    title: str
    kind_label: str
    url: str


_cache: tuple[float, list[GoogleEvent]] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_incidents(payload) -> list[GoogleEvent]:
    events = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        start = _day(item.get("begin"))
        title = (item.get("external_desc") or "").strip()
        if not start or not title:
            continue
        service = item.get("service_name") or ""
        uri = item.get("uri") or ""
        events.append(GoogleEvent(
            start=start, end=_day(item.get("end")), title=title[:160],
            kind_label=SERVICE_LABELS.get(service, "Incidencia de Google"),
            url=f"https://status.search.google.com/{uri}" if uri.startswith("incidents/") else "https://status.search.google.com/",
        ))
    events.sort(key=lambda e: e.start)
    return events


async def _fetch() -> list[GoogleEvent]:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.get(INCIDENTS_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
        return parse_incidents(response.json())


async def google_events(start: date, end: date) -> tuple[list[GoogleEvent], bool]:
    """Eventos que tocan [start, end] y si el panel de Google respondió."""
    global _cache
    now = time.monotonic()
    available = True
    if _cache is None or now - _cache[0] > CACHE_SECONDS:
        try:
            _cache = (now, await _fetch())
        except Exception as exc:  # red, JSON o HTTP: nunca rompe la pantalla
            logger.warning("Google Search status unavailable: %s", type(exc).__name__)
            available = False
            if _cache is None:
                return [], False
    events = [e for e in _cache[1] if e.start <= end and (e.end or e.start) >= start]
    return events, available
