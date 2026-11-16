"""Bing Webmaster Tools en vivo: rastreo y rendimiento de las URLs clave de un cliente.

Cada web tiene su propia cuenta de Bing, así que la API key se guarda por
cliente (`client_bing_connections`, cifrada) junto con el sitio de esa cuenta
que es la web del cliente. Las cifras NO se guardan: cada comprobación pregunta
a Bing, a petición de la persona (gasta cuota de la propiedad en Bing).

Para qué sirve: ChatGPT y Copilot sacan candidatos de los resultados de Bing
antes de elegir qué citar. Una URL que Bing no ha rastreado difícilmente entra
en ese primer paso. Es un requisito, no una medida de visibilidad en IA.

URLs que se miran: las vigiladas activas del cliente (`web_watches`, como
mucho `MAX_URLS`) o, sin ninguna, su web (`Client.website`).

API: `https://ssl.bing.com/webmaster/api.svc/json/<Método>?apikey=…`. Responde
`{"d": …}` y fechas `/Date(ms)/`; los errores llegan como
`{"ErrorCode": n, "Message": "…"}` (3 = clave no válida, 4/5 = cuota). La
clave va en la URL: nunca sale en un mensaje ni en el log de httpx.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import decrypt_vault_secret
from backend.db.models import Client, ClientBingConnection, WebWatch
from backend.services.gsc_live import _belongs, _domain
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

API_BASE = "https://ssl.bing.com/webmaster/api.svc/json/"
TIMEOUT_SECONDS = 15
# Peticiones a Bing a la vez en una comprobación.
CONCURRENCY = 4
MAX_URLS = 25
# Ventana del rendimiento: los últimos 28 días con datos (como Control SEO).
WINDOW_DAYS = 28
TOP_QUERIES = 10

# ApiErrorCode de Bing.
_INVALID_KEY = 3
_THROTTLED = (4, 5)
_NOT_FOUND = (7, 11)  # InvalidUrl, NotFound
_NOT_AUTHORIZED = (13, 14)

_DATE_RE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
_KEY_RE = re.compile(r"(apikey=)[^&\s]+", re.IGNORECASE)


class _ApiKeyLogRedaction(logging.Filter):
    """httpx escribe la URL de cada petición en el log (INFO) y la clave va en ella."""

    def filter(self, record):
        record.msg = _KEY_RE.sub(r"\1[redacted]", str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(_KEY_RE.sub(r"\1[redacted]", str(a)) if isinstance(a, (str, httpx.URL)) else a
                                for a in record.args)
        return True


logging.getLogger("httpx").addFilter(_ApiKeyLogRedaction())


class BingError(Exception):
    """Error que la ruta devuelve tal cual: código HTTP, código y mensaje legible."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _ApiError(Exception):
    """Error de una llamada concreta a Bing (antes de decidir qué significa)."""

    def __init__(self, code: int | None, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── Llamadas a Bing ──────────────────────────────────────────────────


def _transport() -> httpx.AsyncBaseTransport | None:
    """Punto de enganche de los tests (nunca salen a la red)."""
    return None


async def _call(http: httpx.AsyncClient, api_key: str, method: str, **params: str) -> Any:
    try:
        response = await http.get(API_BASE + method, params={"apikey": api_key, **params})
    except httpx.TimeoutException as exc:
        raise _ApiError(None, "Bing no ha respondido a tiempo") from exc
    except httpx.HTTPError as exc:
        raise _ApiError(None, "No se ha podido conectar con Bing") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400 or (isinstance(payload, dict) and "ErrorCode" in payload):
        code = payload.get("ErrorCode") if isinstance(payload, dict) else None
        message = payload.get("Message") if isinstance(payload, dict) else None
        message = _KEY_RE.sub(r"\1[redacted]", str(message or f"HTTP {response.status_code}"))
        raise _ApiError(code if isinstance(code, int) else None, message.removeprefix("ERROR!!! ")[:300])
    if not isinstance(payload, dict) or "d" not in payload:
        raise _ApiError(None, "Bing ha devuelto una respuesta inesperada")
    return payload["d"]


def _fatal(exc: _ApiError) -> BingError | None:
    """Los errores que valen para toda la comprobación (no sólo para una URL)."""
    if exc.code == _INVALID_KEY:
        return BingError(409, "invalid_key", "Bing no acepta la clave de esta web. Hay que cambiarla.")
    if exc.code in _THROTTLED:
        return BingError(429, "rate_limited", "Se ha agotado la cuota de Bing de esta web. Prueba más tarde.")
    if exc.code in _NOT_AUTHORIZED:
        return BingError(409, "site_lost", "La cuenta de Bing ya no tiene acceso a este sitio.")
    return None


def _http_error(exc: _ApiError) -> BingError:
    return _fatal(exc) or BingError(502, "bing_error", f"Bing ha devuelto un error: {exc.message}")


# ── Lectura de lo que devuelve Bing ──────────────────────────────────


def parse_date(value: Any) -> datetime | None:
    """`/Date(1699999999000)/` → datetime UTC. La fecha mínima de .NET es "sin fecha"."""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.fullmatch(value.strip())
    if not match:
        return None
    moment = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)
    return moment if moment.year >= 2000 else None


def page_key(url: str) -> str:
    """Clave para cruzar URLs: sin esquema, `www.`, query, fragmento ni barra final."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}"


def url_state(info: dict | None) -> dict:
    """Estado de una URL según `GetUrlInfo`."""
    info = info or {}
    crawled = parse_date(info.get("LastCrawledDate"))
    discovered = parse_date(info.get("DiscoveryDate"))
    http_status = info.get("HttpStatus") if isinstance(info.get("HttpStatus"), int) else None
    if crawled is not None:
        if http_status and 300 <= http_status < 400:
            state = "redirect"
        elif http_status and http_status >= 400:
            state = "crawl_error"
        else:
            state = "crawled"
    elif discovered is not None:
        state = "discovered"
    else:
        state = "unknown"
    return {
        "state": state,
        "http_status": http_status or None,
        "last_crawled_at": crawled.isoformat() if crawled else None,
        "discovered_at": discovered.isoformat() if discovered else None,
    }


def aggregate(rows: list[dict], key_fn) -> dict[str, dict]:
    """Suma impresiones y clics de los últimos `WINDOW_DAYS` días con datos.

    La posición es la media ponderada por impresiones (`AvgImpressionPosition`;
    Bing pone -1 o 0 cuando no hay). La ventana acaba en la fecha más reciente
    que trae Bing, no hoy: sus datos llegan con retraso.
    """
    dated = [(parse_date(r.get("Date")), r) for r in rows if isinstance(r, dict)]
    dated = [(d, r) for d, r in dated if d is not None]
    if not dated:
        return {}
    end = max(d for d, _ in dated)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    out: dict[str, dict] = {}
    for moment, row in dated:
        if moment.date() < start.date():
            continue
        key = key_fn(str(row.get("Query") or ""))
        if not key:
            continue
        acc = out.setdefault(key, {"impressions": 0, "clicks": 0, "_weighted": 0.0, "_weight": 0})
        impressions = int(row.get("Impressions") or 0)
        acc["impressions"] += impressions
        acc["clicks"] += int(row.get("Clicks") or 0)
        position = row.get("AvgImpressionPosition")
        if isinstance(position, (int, float)) and position > 0 and impressions > 0:
            acc["_weighted"] += float(position) * impressions
            acc["_weight"] += impressions
    for acc in out.values():
        weight = acc.pop("_weight")
        weighted = acc.pop("_weighted")
        acc["position"] = round(weighted / weight, 1) if weight else None
    return out


def _window(rows: list[dict]) -> dict | None:
    dates = [d for d in (parse_date(r.get("Date")) for r in rows if isinstance(r, dict)) if d is not None]
    if not dates:
        return None
    end = max(dates).date()
    return {"start": (end - timedelta(days=WINDOW_DAYS - 1)).isoformat(), "end": end.isoformat()}


# ── Conexión ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Connection:
    api_key: str
    site_url: str


async def connection_for(db: AsyncSession, client: Client) -> tuple[ClientBingConnection, Connection]:
    row = await db.get(ClientBingConnection, client.id)
    if row is None:
        raise BingError(409, "not_connected", "Esta web no tiene Bing conectado.")
    return row, Connection(api_key=decrypt_vault_secret(row.api_key), site_url=row.site_url)


def suggested_site(sites: list[str], client: Client) -> str | None:
    """El sitio de la cuenta que es la web del cliente: primero el exacto, luego por dominio."""
    for reference in (client.website, client.gsc_url):
        if not reference:
            continue
        exact = page_key(reference)
        for site in sites:
            if page_key(site) == exact:
                return site
    for reference in (client.website, client.gsc_url):
        domain = _domain(reference) if reference else None
        if domain:
            matches = [s for s in sites if _belongs(s, domain)]
            if matches:
                # El de menos subdominios (www.x.com antes que blog.x.com).
                return min(matches, key=lambda s: (len(_domain(s) or ""), s))
    return None


async def user_sites(api_key: str) -> list[str]:
    """Sitios VERIFICADOS de la cuenta de esa clave (`GetUserSites`)."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=_transport()) as http:
        try:
            sites = await _call(http, api_key, "GetUserSites")
        except _ApiError as exc:
            if exc.code == _INVALID_KEY:
                raise BingError(422, "invalid_key", "Bing no acepta esta clave. Revisa que esté completa.") from exc
            raise _http_error(exc) from exc
    urls = []
    for site in sites or []:
        if isinstance(site, dict) and site.get("IsVerified") is not False and isinstance(site.get("Url"), str):
            urls.append(site["Url"])
    return sorted(set(urls))


# ── Comprobación ─────────────────────────────────────────────────────


async def urls_for(db: AsyncSession, client: Client) -> tuple[list[dict], int]:
    """URLs a comprobar (`[{url, label}]`) y cuántas vigiladas activas hay en total."""
    watches = (await db.execute(
        select(WebWatch.url, WebWatch.label)
        .where(WebWatch.client_id == client.id, WebWatch.is_active.is_(True), WebWatch.archived_at.is_(None))
        .order_by(WebWatch.created_at, WebWatch.url)
    )).all()
    if watches:
        return [{"url": w.url, "label": w.label} for w in watches[:MAX_URLS]], len(watches)
    if client.website:
        website = client.website.strip()
        if not website.startswith(("http://", "https://")):
            website = "https://" + website
        return [{"url": website, "label": None}], 0
    return [], 0


async def _record(db: AsyncSession, row: ClientBingConnection, error: BingError | None) -> None:
    status, message = ("invalid", error.message) if error and error.code == "invalid_key" else ("ok", None)
    if (row.status, row.last_error) != (status, message):
        row.status, row.last_error = status, message
        await db.commit()


async def check(db: AsyncSession, client: Client) -> dict:
    """Rastreo (`GetUrlInfo`) de cada URL y su rendimiento (`GetPageStats`, una llamada)."""
    row, conn = await connection_for(db, client)
    targets, watched_total = await urls_for(db, client)
    # Nada de transacción abierta mientras se espera a Bing.
    await db.commit()
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=_transport()) as http:
        async def info(url: str) -> dict:
            async with semaphore:
                try:
                    return url_state(await _call(http, conn.api_key, "GetUrlInfo", siteUrl=conn.site_url, url=url))
                except _ApiError as exc:
                    if _fatal(exc):
                        raise
                    if exc.code in _NOT_FOUND:
                        return url_state(None)
                    return {**url_state(None), "state": "error", "error": exc.message}

        stats_task = _call(http, conn.api_key, "GetPageStats", siteUrl=conn.site_url)
        results = await asyncio.gather(stats_task, *(info(t["url"]) for t in targets), return_exceptions=True)
    failed = next((r for r in results if isinstance(r, BaseException)), None)
    if isinstance(failed, _ApiError):
        error = _http_error(failed)
        await _record(db, row, error)
        raise error from failed
    if failed is not None:
        raise failed

    await _record(db, row, None)
    page_rows = results[0] or []
    traffic = aggregate(page_rows, page_key)
    today = business_today()
    urls = []
    for target, state in zip(targets, results[1:]):
        crawled = state.get("last_crawled_at")
        days = (today - datetime.fromisoformat(crawled).date()).days if crawled else None
        perf = traffic.get(page_key(target["url"]))
        urls.append({
            **target, **state,
            "days_since_crawl": days,
            # Sin fila en GetPageStats no hay medida: null, no un cero inventado.
            "impressions": perf["impressions"] if perf else None,
            "clicks": perf["clicks"] if perf else None,
            "position": perf["position"] if perf else None,
        })
    return {
        "site_url": conn.site_url,
        "checked_at": datetime.now(UTC).isoformat(),
        "window": _window(page_rows),
        "watched_total": watched_total,
        "max_urls": MAX_URLS,
        "urls": urls,
    }


async def page_queries(db: AsyncSession, client: Client, url: str) -> dict:
    """Consultas de Bing de una de las URLs que se comprueban (`GetPageQueryStats`)."""
    targets, _ = await urls_for(db, client)
    if page_key(url) not in {page_key(t["url"]) for t in targets}:
        raise BingError(422, "unknown_url", "Esa URL no es de las que se comprueban en Bing.")
    row, conn = await connection_for(db, client)
    await db.commit()
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=_transport()) as http:
        try:
            rows = await _call(http, conn.api_key, "GetPageQueryStats", siteUrl=conn.site_url, page=url)
        except _ApiError as exc:
            error = _http_error(exc)
            await _record(db, row, error)
            raise error from exc
    rows = rows or []
    by_query = aggregate(rows, lambda q: q.strip().lower())
    top = sorted(by_query.items(), key=lambda kv: (-kv[1]["impressions"], kv[0]))[:TOP_QUERIES]
    return {"url": url, "window": _window(rows), "queries": [{"query": q, **v} for q, v in top]}

