"""Search Console en vivo: propiedades de un cliente y `searchanalytics.query`.

A diferencia de la importación diaria (totales y detalle), aquí no se guarda nada:
cada llamada pregunta a Google con la cuenta conectada que mejor ve la
propiedad y devuelve lo que contesta. Lo usan las herramientas `gsc_query` y
`gsc_properties` del MCP, a petición de la persona, para cualquier periodo de
los 16 meses que guarda Google y con cualquier combinación de dimensiones (lo
guardado sólo cubre 120 días y no tiene país ni dispositivo).

Es lo único de Search Console que llega a la IA (política de privacidad,
"Para qué los usamos"). El detalle GUARDADO sigue fuera: lo vigila
`test_el_detalle_de_search_console_no_llega_a_la_ia`.

Propiedades de un cliente: la de `Client.gsc_url` (la principal) y cualquier
otra que vea una cuenta conectada en su mismo dominio o en un subdominio
(p. ej. `sc-domain:x.com` y `https://www.x.com/`).

Totales: segunda llamada SIN dimensiones con los mismos filtros. Sumar las
filas no vale: Google omite las consultas anonimizadas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import select

from backend.db.models import Client, GscConnection
from backend.services import gsc_service
from backend.services.gsc_service import GscAuthError, GscSiteError
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

Dimension = Literal["date", "query", "page", "country", "device", "searchAppearance"]
# Google no filtra por fecha: el periodo ya la acota.
FilterDimension = Literal["query", "page", "country", "device", "searchAppearance"]
Operator = Literal["equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex"]
SearchType = Literal["web", "image", "video", "news", "discover", "googleNews"]
Aggregation = Literal["auto", "byPage", "byProperty"]
DataState = Literal["final", "all"]
MAX_DIMENSIONS = 3
MAX_ROW_LIMIT = 25000
# Lo que guarda Search Console (16 meses), el mismo margen que la importación.
HISTORY_DAYS = gsc_service.BACKFILL_DAYS
# `execute(num_retries=...)` reintenta los 429 y 5xx con espera exponencial.
NUM_RETRIES = 4
# Días que se miran para saber hasta cuándo hay datos.
LATEST_LOOKBACK_DAYS = 10
# Lo que ve cada cuenta cambia poco: se reutiliza unos minutos entre llamadas.
SITES_TTL_SECONDS = 300

_PERMISSION_RANK = gsc_service._PERMISSION_RANK
_sites_cache: dict[tuple[int, str], tuple[float, list[dict]]] = {}


class GscLiveError(Exception):
    """Error que la ruta devuelve tal cual: código HTTP, código y mensaje legible."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Property:
    site_url: str
    is_default: bool
    permission_level: str | None = None
    connection_id: int | None = None
    token: str | None = None

    @property
    def type(self) -> str:
        return "domain" if self.site_url.startswith("sc-domain:") else "url_prefix"


def _domain(site_url: str) -> str | None:
    """'sc-domain:x.com' → 'x.com'; 'https://www.x.com/blog/' → 'x.com'."""
    if site_url.startswith("sc-domain:"):
        host = site_url.removeprefix("sc-domain:")
    else:
        host = urlsplit(site_url).hostname or ""
    host = host.strip().lower().rstrip(".").removeprefix("www.")
    return host or None


def _belongs(site_url: str, domain: str) -> bool:
    other = _domain(site_url)
    return other is not None and (other == domain or other.endswith("." + domain))


# ── Llamadas a Google (en un hilo) ───────────────────────────────────


def _google_message(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason or exc)[:500]


def _execute_sync(token: str, site_url: str, body: dict) -> dict:
    from googleapiclient.errors import HttpError

    try:
        service = gsc_service._service(token)
        return service.searchanalytics().query(siteUrl=site_url, body=body).execute(num_retries=NUM_RETRIES)
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 400:
            # Combinación que Google no admite (regex mal escrita, byProperty con página…).
            raise GscLiveError(422, "invalid_query",
                               f"Search Console rechaza la consulta: {_google_message(exc)}") from exc
        raise gsc_service._translate(exc) from exc
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise gsc_service._translate(exc) from exc


async def _execute(token: str, site_url: str, body: dict) -> dict:
    return await asyncio.to_thread(_execute_sync, token, site_url, body)


async def _sites(connection_id: int, token: str, list_fn) -> list[dict]:
    key = (connection_id, token)
    cached = _sites_cache.get(key)
    if cached and time.monotonic() - cached[0] < SITES_TTL_SECONDS:
        return cached[1]
    sites = await list_fn(token)
    _sites_cache[key] = (time.monotonic(), sites)
    return sites


async def latest_date(token: str, site_url: str, *, data_state: str = "final",
                      search_type: str = "web", today: date | None = None) -> date | None:
    """Último día con datos (del `data_state` pedido) en los últimos días."""
    end = today or business_today()
    result = await _execute(token, site_url, {
        "startDate": (end - timedelta(days=LATEST_LOOKBACK_DAYS)).isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date"],
        "type": search_type,
        "dataState": data_state,
        "rowLimit": LATEST_LOOKBACK_DAYS + 1,
    })
    days = [row["keys"][0] for row in result.get("rows", []) if row.get("keys")]
    return date.fromisoformat(max(days)) if days else None


# ── Propiedades ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClientProperties:
    properties: list[Property]
    # Cuentas que Google rechaza: si la propiedad no la ve nadie, puede ser por eso.
    reconnect_emails: list[str]


async def client_properties(db, client: Client, *, list_fn=gsc_service.list_sites) -> ClientProperties:
    """La principal primero (aunque ninguna cuenta la vea) y luego las de su dominio.

    Cierra la transacción antes de llamar a Google.
    """
    default = gsc_service.normalize_site_url(client.gsc_url)
    if default is None:
        raise GscLiveError(409, "no_property",
                           f"El cliente #{client.id} {client.name} no tiene propiedad de Search Console "
                           "(se pone en Ajustes del cliente).")
    connections = (await db.scalars(select(GscConnection).order_by(GscConnection.id))).all()
    connected = [(c.id, c.refresh_token, c.google_email) for c in connections if c.status == "connected"]
    has_any = bool(connections)
    await db.commit()
    if not connected:
        if has_any:
            raise GscLiveError(409, "reconnect_required",
                               "Las cuentas de Search Console necesitan reconectarse (Ajustes → Search Console).")
        raise GscLiveError(409, "not_connected",
                           "Search Console no está conectado (un admin lo conecta en Ajustes → Search Console).")

    results = await asyncio.gather(
        *(_sites(cid, token, list_fn) for cid, token, _ in connected), return_exceptions=True
    )
    domain = _domain(default)
    best: dict[str, tuple[int, Property]] = {}
    reconnect: list[str] = []
    for (cid, token, email), result in zip(connected, results):
        if isinstance(result, GscAuthError):
            reconnect.append(email or f"cuenta #{cid}")
            continue
        if isinstance(result, BaseException):
            logger.warning("Search Console en vivo: no se pudo listar la cuenta %s (%s)", cid,
                           getattr(result, "code", type(result).__name__))
            continue
        for site in result:
            url = site["site_url"]
            if url != default and (domain is None or not _belongs(url, domain)):
                continue
            rank = _PERMISSION_RANK.get(site.get("permission") or "", 3)
            if url not in best or rank < best[url][0]:
                best[url] = (rank, Property(url, url == default, site.get("permission"), cid, token))

    main = best.pop(default, (0, Property(default, True)))[1]
    others = [p for _, p in sorted(best.values(), key=lambda item: item[1].site_url)]
    return ClientProperties([main, *others], reconnect)


def _site_error(exc: Exception, site_url: str) -> GscLiveError:
    if isinstance(exc, GscLiveError):
        return exc
    if isinstance(exc, GscAuthError):
        return GscLiveError(409, "reconnect_required",
                            f"La cuenta de Google que ve {site_url} necesita reconectarse "
                            "(Ajustes → Search Console).")
    code = getattr(exc, "code", "api_error")
    if code in ("no_access", "not_found"):
        return GscLiveError(403, "no_access", f"La cuenta conectada no tiene permiso sobre {site_url}.")
    if code == "rate_limited":
        return GscLiveError(429, "rate_limited",
                            "Google limita las consultas de Search Console ahora mismo. Prueba en un minuto.")
    return GscLiveError(502, "google_error", f"Search Console no ha respondido bien para {site_url}. "
                                             "Prueba de nuevo en un momento.")


def pick_property(found: ClientProperties, requested: str | None) -> Property:
    """La pedida (si es del cliente) o la principal, con una cuenta que la vea."""
    if requested:
        wanted = gsc_service.normalize_site_url(requested)
        match = next((p for p in found.properties if p.site_url == wanted), None)
        if match is None:
            options = ", ".join(p.site_url for p in found.properties)
            raise GscLiveError(422, "unknown_property",
                               f"{requested} no es una propiedad de este cliente. Las suyas: {options}.")
    else:
        match = found.properties[0]
    if match.token is None:
        hint = (f" Hay cuentas que necesitan reconectarse: {', '.join(found.reconnect_emails)}."
                if found.reconnect_emails else "")
        raise GscLiveError(403, "no_access",
                           f"Ninguna cuenta de Google conectada tiene permiso sobre {match.site_url}.{hint}")
    return match


def check_dates(start: date, end: date, *, today: date | None = None) -> None:
    today = today or business_today()
    earliest = today - timedelta(days=HISTORY_DAYS)
    if start > end:
        raise GscLiveError(422, "invalid_dates", "start_date no puede ser posterior a end_date.")
    if end > today:
        raise GscLiveError(422, "invalid_dates", f"end_date no puede ser posterior a hoy ({today.isoformat()}).")
    if start < earliest:
        raise GscLiveError(422, "out_of_range",
                           f"Search Console sólo guarda 16 meses: start_date tiene que ser {earliest.isoformat()} "
                           "o posterior.")


def _metrics(row: dict) -> dict:
    return {
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr"),
        "position": row.get("position"),
    }


async def query(db, client: Client, *, start_date: date, end_date: date, dimensions: list[str],
                search_type: str = "web", filters: list[dict] | None = None,
                aggregation_type: str = "auto", data_state: str = "final", row_limit: int = 1000,
                start_row: int = 0, property_url: str | None = None,
                list_fn=gsc_service.list_sites, today: date | None = None) -> dict[str, Any]:
    """`searchanalytics.query` con totales del mismo filtro y periodo (sin dimensiones)."""
    check_dates(start_date, end_date, today=today)
    prop = pick_property(await client_properties(db, client, list_fn=list_fn), property_url)

    base: dict[str, Any] = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "type": search_type,
        "aggregationType": aggregation_type,
        "dataState": data_state,
    }
    if filters:
        base["dimensionFilterGroups"] = [{"groupType": "and", "filters": [
            {"dimension": f["dimension"], "operator": f["operator"], "expression": f["expression"]}
            for f in filters
        ]}]
    rows_body = {**base, "dimensions": list(dimensions), "rowLimit": row_limit, "startRow": start_row}
    try:
        result, totals, latest = await asyncio.gather(
            _execute(prop.token, prop.site_url, rows_body),
            _execute(prop.token, prop.site_url, {**base, "rowLimit": 1}),
            latest_date(prop.token, prop.site_url, data_state=data_state, search_type=search_type, today=today),
        )
    except (GscLiveError, GscAuthError, GscSiteError) as exc:
        raise _site_error(exc, prop.site_url) from exc

    rows = [
        {"keys": dict(zip(dimensions, row.get("keys", []))), **_metrics(row)}
        for row in result.get("rows", [])
    ]
    total_rows = totals.get("rows") or [{}]
    has_more = len(rows) == row_limit
    return {
        "property": prop.site_url,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "search_type": search_type,
        "data_state": data_state,
        "data_available_until": latest.isoformat() if latest else None,
        "dimensions": list(dimensions),
        "rows": rows,
        "totals": _metrics(total_rows[0]),
        "row_count": len(rows),
        "has_more": has_more,
        "next_start_row": start_row + len(rows) if has_more else None,
    }


async def properties(db, client: Client, *, list_fn=gsc_service.list_sites,
                     today: date | None = None) -> dict[str, Any]:
    """Propiedades del cliente con su permiso y el último día con datos finales."""
    found = await client_properties(db, client, list_fn=list_fn)

    async def until(prop: Property) -> tuple[str | None, str | None]:
        if prop.token is None:
            return None, "no_access"
        try:
            latest = await latest_date(prop.token, prop.site_url, today=today)
        except (GscLiveError, GscAuthError, GscSiteError) as exc:
            return None, _site_error(exc, prop.site_url).code
        return (latest.isoformat() if latest else None), None

    dates = await asyncio.gather(*(until(p) for p in found.properties))
    return {
        "client_id": client.id,
        "client_name": client.name,
        "properties": [
            {
                "property": p.site_url,
                "type": p.type,
                "is_default": p.is_default,
                "permission_level": p.permission_level,
                "data_available_until": latest,
                "error": error,
            }
            for p, (latest, error) in zip(found.properties, dates)
        ],
        "reconnect_required": found.reconnect_emails,
    }
