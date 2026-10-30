"""GA4 en vivo: la propiedad de un cliente y `properties.runReport` de la Data API.

Gemelo de `gsc_live.py`. A diferencia de la importación diaria de GA4 (totales
por día), aquí no se guarda nada: cada llamada pregunta a Google con la cuenta
conectada que ve la propiedad y devuelve lo que contesta. Lo usan las
herramientas `ga4_query` y `ga4_properties` del MCP, a petición de la persona,
para cualquier periodo y con cualquier combinación de las dimensiones y
métricas permitidas (canal, landing, fuente/medio, campaña, dispositivo…).

Nunca lee lo importado: sólo `Client.ga4_property_id` y las cuentas conectadas
(`gsc_connection`, las mismas que Search Console con el permiso de Analytics).

Totales: la agregación TOTAL del mismo informe (`metricAggregations`), que GA4
calcula bien también para las métricas de proporción (engagementRate) y la
duración media; sumar filas no valdría para ésas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, get_args

from sqlalchemy import select

from backend.db.models import Client, GscConnection
from backend.services import ga4_service
from backend.services.ga4_service import Ga4Error
from backend.services.gsc_service import GscAuthError
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

Dimension = Literal[
    "date", "sessionDefaultChannelGroup", "firstUserDefaultChannelGroup", "landingPage",
    "landingPagePlusQueryString", "pagePath", "sessionSource", "sessionMedium", "sessionSourceMedium",
    "sessionCampaignName", "deviceCategory", "country", "city", "eventName",
]
Metric = Literal[
    "sessions", "engagedSessions", "keyEvents", "newUsers", "totalUsers", "activeUsers",
    "screenPageViews", "engagementRate", "eventCount", "averageSessionDuration",
]
Operator = Literal["equals", "contains", "regex", "notEquals", "notContains", "notRegex"]
DIMENSIONS: frozenset[str] = frozenset(get_args(Dimension))
METRICS: frozenset[str] = frozenset(get_args(Metric))
MAX_DIMENSIONS = 5
MAX_METRICS = 10
MAX_LIMIT = 100000
# Operador → (matchType de GA4, negado). La regex casa con el valor ENTERO.
_MATCH: dict[str, tuple[str, bool]] = {
    "equals": ("EXACT", False),
    "contains": ("CONTAINS", False),
    "regex": ("FULL_REGEXP", False),
    "notEquals": ("EXACT", True),
    "notContains": ("CONTAINS", True),
    "notRegex": ("FULL_REGEXP", True),
}
# `execute(num_retries=...)` reintenta los 429 y 5xx con espera exponencial.
NUM_RETRIES = 4
# Días que se miran para saber hasta cuándo hay datos.
LATEST_LOOKBACK_DAYS = 10
# Lo que ve cada cuenta cambia poco: se reutiliza unos minutos entre llamadas.
PROPERTIES_TTL_SECONDS = 300

_properties_cache: dict[tuple[int, str], tuple[float, list[str]]] = {}


class Ga4LiveError(Exception):
    """Error que la ruta devuelve tal cual: código HTTP, código y mensaje legible."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ── Llamadas a Google (en un hilo) ───────────────────────────────────


def _data_service(token: str):
    from googleapiclient.discovery import build

    return build("analyticsdata", "v1beta", credentials=ga4_service._credentials(token), cache_discovery=False)


def _google_message(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason or exc)[:500]


def _run_report_sync(token: str, property_id: str, body: dict) -> dict:
    from googleapiclient.errors import HttpError

    try:
        service = _data_service(token)
        return service.properties().runReport(
            property=f"properties/{property_id}", body=body).execute(num_retries=NUM_RETRIES)
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 400:
            # Combinación que GA4 no admite (dimensión y métrica incompatibles, regex mal escrita…).
            raise Ga4LiveError(422, "invalid_query",
                               f"GA4 rechaza la consulta: {_google_message(exc)}") from exc
        raise ga4_service._translate(exc) from exc
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise ga4_service._translate(exc) from exc


async def _run_report(token: str, property_id: str, body: dict) -> dict:
    return await asyncio.to_thread(_run_report_sync, token, property_id, body)


async def _visible(connection_id: int, token: str, list_fn) -> list[str]:
    key = (connection_id, token)
    cached = _properties_cache.get(key)
    if cached and time.monotonic() - cached[0] < PROPERTIES_TTL_SECONDS:
        return cached[1]
    found = await list_fn(token)
    _properties_cache[key] = (time.monotonic(), found)
    return found


def _iso_day(value: str) -> str:
    """'20261025' → '2026-10-25' (GA4 devuelve la dimensión date sin guiones)."""
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


async def latest_date(token: str, property_id: str, *, today: date | None = None) -> date | None:
    """Último día con datos en los últimos días (el de hoy y ayer pueden estar a medias)."""
    end = today or business_today()
    result = await _run_report(token, property_id, {
        "dateRanges": [{"startDate": (end - timedelta(days=LATEST_LOOKBACK_DAYS)).isoformat(),
                        "endDate": end.isoformat()}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "sessions"}],
        "keepEmptyRows": False,
        "limit": LATEST_LOOKBACK_DAYS + 1,
    })
    days = [row["dimensionValues"][0]["value"] for row in result.get("rows", []) if row.get("dimensionValues")]
    return date.fromisoformat(_iso_day(max(days))) if days else None


# ── Propiedad del cliente ────────────────────────────────────────────


@dataclass(frozen=True)
class ClientProperty:
    property_id: str
    connection_id: int | None
    token: str | None
    email: str | None
    # Cuentas que Google rechaza o sin permiso de Analytics: si nadie ve la propiedad, puede ser por eso.
    reconnect_emails: list[str]
    missing_scope_emails: list[str]


async def client_property(db, client: Client, *, list_fn=ga4_service.list_properties) -> ClientProperty:
    """La propiedad del cliente y la primera cuenta conectada que la ve.

    Cierra la transacción antes de llamar a Google.
    """
    property_id = ga4_service.normalize_property(client.ga4_property_id)
    if property_id is None:
        raise Ga4LiveError(409, "no_property",
                           f"El cliente #{client.id} {client.name} no tiene propiedad de GA4 "
                           "(se pone en Ajustes del cliente).")
    connections = (await db.scalars(select(GscConnection).order_by(GscConnection.id))).all()
    connected = [(c.id, c.refresh_token, c.google_email) for c in connections if c.status == "connected"]
    has_any = bool(connections)
    await db.commit()
    if not connected:
        if has_any:
            raise Ga4LiveError(409, "reconnect_required",
                               "Las cuentas de Google necesitan reconectarse (Ajustes → Search Console).")
        raise Ga4LiveError(409, "not_connected",
                           "No hay ninguna cuenta de Google conectada (un admin la conecta en "
                           "Ajustes → Search Console, con el permiso de Analytics).")

    results = await asyncio.gather(
        *(_visible(cid, token, list_fn) for cid, token, _ in connected), return_exceptions=True
    )
    reconnect: list[str] = []
    missing_scope: list[str] = []
    seen_by: tuple[int, str, str | None] | None = None
    for (cid, token, email), result in zip(connected, results):
        label = email or f"cuenta #{cid}"
        if isinstance(result, GscAuthError):
            reconnect.append(label)
            continue
        if isinstance(result, Ga4Error) and result.code == "missing_scope":
            missing_scope.append(label)
            continue
        if isinstance(result, BaseException):
            logger.warning("GA4 en vivo: no se pudo listar la cuenta %s (%s)", cid,
                           getattr(result, "code", type(result).__name__))
            continue
        if seen_by is None and property_id in result:
            seen_by = (cid, token, email)
    cid, token, email = seen_by or (None, None, None)
    return ClientProperty(property_id, cid, token, email, reconnect, missing_scope)


def _no_account_error(found: ClientProperty) -> Ga4LiveError:
    hint = (f" Hay cuentas que necesitan reconectarse: {', '.join(found.reconnect_emails)}."
            if found.reconnect_emails else "")
    if found.missing_scope_emails:
        return Ga4LiveError(403, "missing_scope",
                            f"Ninguna cuenta conectada ve la propiedad de GA4 {found.property_id}, y "
                            f"{', '.join(found.missing_scope_emails)} no tiene aún el permiso de Analytics: "
                            f"un admin tiene que reconectarla en Ajustes → Search Console para darlo.{hint}")
    return Ga4LiveError(403, "no_access",
                        f"Ninguna cuenta de Google conectada tiene permiso sobre la propiedad de GA4 "
                        f"{found.property_id}.{hint}")


def _property_error(exc: Exception, property_id: str) -> Ga4LiveError:
    if isinstance(exc, Ga4LiveError):
        return exc
    if isinstance(exc, GscAuthError):
        return Ga4LiveError(409, "reconnect_required",
                            f"La cuenta de Google que ve la propiedad de GA4 {property_id} necesita "
                            "reconectarse (Ajustes → Search Console).")
    code = getattr(exc, "code", "api_error")
    if code == "missing_scope":
        return Ga4LiveError(403, "missing_scope",
                            "La cuenta de Google que ve la propiedad no tiene el permiso de Analytics: un admin "
                            "tiene que reconectarla en Ajustes → Search Console para darlo.")
    if code in ("no_access", "not_found"):
        return Ga4LiveError(403, "no_access", f"La cuenta conectada no tiene permiso sobre la propiedad de GA4 "
                                              f"{property_id}.")
    if code == "rate_limited":
        return Ga4LiveError(429, "rate_limited",
                            "Google limita las consultas de GA4 ahora mismo. Prueba en un minuto.")
    return Ga4LiveError(502, "google_error", f"GA4 no ha respondido bien para la propiedad {property_id}. "
                                             "Prueba de nuevo en un momento.")


def pick_property(found: ClientProperty, requested: str | None) -> ClientProperty:
    """La del cliente (si se pide otra, error) con una cuenta que la vea."""
    if requested is not None and ga4_service.normalize_property(requested) != found.property_id:
        raise Ga4LiveError(422, "unknown_property",
                           f"{requested} no es la propiedad de GA4 de este cliente (la suya: {found.property_id}).")
    if found.token is None:
        raise _no_account_error(found)
    return found


# ── Consulta ─────────────────────────────────────────────────────────


def check_dates(start: date, end: date, *, today: date | None = None) -> None:
    """Sólo orden y nada futuro: la retención depende de cada propiedad (GA4 dice si no hay datos)."""
    today = today or business_today()
    if start > end:
        raise Ga4LiveError(422, "invalid_dates", "start_date no puede ser posterior a end_date.")
    if end > today:
        raise Ga4LiveError(422, "invalid_dates", f"end_date no puede ser posterior a hoy ({today.isoformat()}).")


def _invalid(message: str) -> Ga4LiveError:
    return Ga4LiveError(422, "invalid_query", message)


def check_request(dimensions: list[str], metrics: list[str], filters: list[dict],
                  limit: int, offset: int, order_by: list[dict]) -> None:
    """Lo mismo que valida la ruta, para quien llame al servicio directamente."""
    if len(dimensions) > MAX_DIMENSIONS or len(set(dimensions)) != len(dimensions):
        raise _invalid(f"Hasta {MAX_DIMENSIONS} dimensiones, cada una una sola vez.")
    if not 1 <= len(metrics) <= MAX_METRICS or len(set(metrics)) != len(metrics):
        raise _invalid(f"Entre 1 y {MAX_METRICS} métricas, cada una una sola vez.")
    unknown = [d for d in dimensions if d not in DIMENSIONS] + [m for m in metrics if m not in METRICS]
    unknown += [f.get("dimension") for f in filters if f.get("dimension") not in DIMENSIONS]
    if unknown:
        raise _invalid(f"No se admite: {', '.join(map(str, unknown))}.")
    bad_ops = [f.get("operator") for f in filters if f.get("operator") not in _MATCH]
    if bad_ops:
        raise _invalid(f"Operador no válido: {', '.join(map(str, bad_ops))}.")
    if any(not f.get("expression") for f in filters):
        raise _invalid("Cada filtro necesita una expresión.")
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise _invalid(f"limit va de 1 a {MAX_LIMIT} y offset no puede ser negativo.")
    loose = [o.get("field") for o in order_by if o.get("field") not in (*dimensions, *metrics)]
    if loose:
        raise _invalid(f"Sólo se ordena por dimensiones o métricas pedidas: {', '.join(map(str, loose))}.")


def _filter_expression(f: dict) -> dict:
    match_type, negated = _MATCH[f["operator"]]
    expression = {"filter": {"fieldName": f["dimension"],
                             "stringFilter": {"matchType": match_type, "value": f["expression"]}}}
    return {"notExpression": expression} if negated else expression


def _order_bys(dimensions: list[str], metrics: list[str], order_by: list[dict]) -> list[dict]:
    """Lo pedido; si no, por fecha si va date y si no, por la primera métrica de mayor a menor."""
    if not order_by:
        order_by = ([{"field": "date", "desc": False}] if "date" in dimensions
                    else [{"field": metrics[0], "desc": True}])
    return [
        {"metric": {"metricName": o["field"]}, "desc": bool(o.get("desc"))} if o["field"] in metrics
        else {"dimension": {"dimensionName": o["field"]}, "desc": bool(o.get("desc"))}
        for o in order_by
    ]


def _number(value: Any) -> int | float:
    number = float(value or 0)
    return int(number) if number.is_integer() else number


def _metric_values(row: dict, metrics: list[str]) -> dict[str, int | float]:
    values = [m.get("value") for m in row.get("metricValues", [])]
    return {name: _number(values[i] if i < len(values) else 0) for i, name in enumerate(metrics)}


async def query(db, client: Client, *, start_date: date, end_date: date, dimensions: list[str],
                metrics: list[str], filters: list[dict] | None = None, limit: int = 1000, offset: int = 0,
                order_by: list[dict] | None = None, property_id: str | None = None,
                list_fn=ga4_service.list_properties, today: date | None = None) -> dict[str, Any]:
    """`runReport` con los totales del mismo informe (agregación TOTAL) y el último día con datos."""
    dimensions, metrics, filters, order_by = list(dimensions), list(metrics), list(filters or []), list(order_by or [])
    check_dates(start_date, end_date, today=today)
    check_request(dimensions, metrics, filters, limit, offset, order_by)
    prop = pick_property(await client_property(db, client, list_fn=list_fn), property_id)

    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics": [{"name": m} for m in metrics],
        "metricAggregations": ["TOTAL"],
        "keepEmptyRows": False,
        "limit": limit,
        "offset": offset,
        "orderBys": _order_bys(dimensions, metrics, order_by),
    }
    if filters:
        body["dimensionFilter"] = {"andGroup": {"expressions": [_filter_expression(f) for f in filters]}}
    try:
        result, latest = await asyncio.gather(
            _run_report(prop.token, prop.property_id, body),
            latest_date(prop.token, prop.property_id, today=today),
        )
    except (Ga4LiveError, GscAuthError, Ga4Error) as exc:
        raise _property_error(exc, prop.property_id) from exc

    rows = []
    for row in result.get("rows", []):
        values = [d.get("value") for d in row.get("dimensionValues", [])]
        keys = {d: (_iso_day(v) if d == "date" and v else v) for d, v in zip(dimensions, values)}
        rows.append({"keys": keys, "metrics": _metric_values(row, metrics)})
    totals_rows = result.get("totals") or []
    if totals_rows:
        totals = _metric_values(totals_rows[0], metrics)
    elif not dimensions and rows:
        totals = dict(rows[0]["metrics"])  # sin dimensiones, la única fila ya es el total
    else:
        totals = {m: 0 for m in metrics}
    total_rows = int(result.get("rowCount") or 0)
    has_more = offset + len(rows) < total_rows
    return {
        "property_id": prop.property_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "dimensions": dimensions,
        "metrics": metrics,
        "rows": rows,
        "totals": totals,
        "row_count": len(rows),
        "total_rows": total_rows,
        "has_more": has_more,
        "next_offset": offset + len(rows) if has_more else None,
        "data_available_until": latest.isoformat() if latest else None,
    }


async def properties(db, client: Client, *, list_fn=ga4_service.list_properties,
                     today: date | None = None) -> dict[str, Any]:
    """La propiedad del cliente, la cuenta que la ve y el último día con datos."""
    found = await client_property(db, client, list_fn=list_fn)
    latest, error = None, None
    if found.token is None:
        error = _no_account_error(found).code
    else:
        try:
            day = await latest_date(found.token, found.property_id, today=today)
            latest = day.isoformat() if day else None
        except (Ga4LiveError, GscAuthError, Ga4Error) as exc:
            error = _property_error(exc, found.property_id).code
    return {
        "client_id": client.id,
        "client_name": client.name,
        "property_id": found.property_id,
        "account": found.email,
        "data_available_until": latest,
        "error": error,
        "reconnect_required": found.reconnect_emails,
        "missing_scope": found.missing_scope_emails,
    }
