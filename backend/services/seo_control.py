"""Control SEO por cliente: tráfico de Google por marca, sección, consulta y página.

Lee lo que importan los jobs `gsc` (totales diarios en `gsc_daily`) y
`gsc_detail` (consultas y páginas por día, 120 días). Aquí no se llama a
Google ni a la IA: el detalle de Search Console NO va a ningún camino de IA
(lo promete la política de privacidad; lo vigila
`test_el_detalle_de_search_console_no_llega_a_la_ia`).

Reglas de las cifras (globales):
- Clics e impresiones se SUMAN en la ventana.
- Posición = SUM(posición × impresiones) / SUM(impresiones).
- `position_delta` positivo = mejora (posición anterior − actual).

Ventana: la misma que el estado del cliente (`seo_window`, 28 días por
defecto, o 7). Termina en el último día que tienen a la vez los totales y el
detalle; la anterior son los `days` días justo antes.

Dos trampas del detalle:
- Google anonimiza las consultas poco frecuentes: "sin clasificar" = total de
  `gsc_daily` − suma de consultas (nunca por debajo de 0).
- Las impresiones por página no suman el total de la propiedad (una búsqueda
  que enseña dos páginas cuenta en las dos). Por eso las secciones se reparten
  por clics y sus impresiones sólo se enseñan en absoluto.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import unquote, urlsplit

from sqlalchemy import select, text

from backend.db.models import Client, GscConnection, GscDetailSync, GscSiteSync
from backend.services.gsc_service import normalize_site_url

# Ventana del tráfico: 28 días (4 semanas completas, sin sesgo de día de la semana).
SEO_WINDOW_DAYS = 28
WINDOW_CHOICES = (7, 28)
# Semanas del gráfico de marca (16 × 7 = 112 días, dentro de los 120 del detalle).
TREND_WEEKS = 16
# Mínimo de impresiones para que una consulta/página cuente como "se mueve".
DEFAULT_MIN_IMPRESSIONS = 30
MOVERS_IN_SUMMARY = 5
MAX_LIMIT = 100

# Términos de marca.
MAX_BRAND_TERMS = 20
MIN_TERM_LENGTH = 3
MAX_TERM_LENGTH = 60

SeoStatus = Literal[
    "no_property", "not_connected", "reconnect_required", "not_synced", "backfilling", "error", "ok",
]
MoverSort = Literal["clicks_gain", "clicks_loss", "position_gain", "position_loss"]
BrandFilter = Literal["all", "brand", "non_brand"]


# ── Ventana ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeoWindow:
    start: date
    end: date
    previous_start: date
    previous_end: date
    days: int

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "previous_start": self.previous_start.isoformat(),
            "previous_end": self.previous_end.isoformat(), "days": self.days,
        }


def seo_window(end: date, days: int = SEO_WINDOW_DAYS) -> SeoWindow:
    """`days` días hasta `end` (incluido) y los `days` anteriores.

    La usan el estado del cliente y Control SEO: así las dos cifras coinciden.
    """
    start = end - timedelta(days=days - 1)
    return SeoWindow(
        start=start, end=end,
        previous_start=start - timedelta(days=days),
        previous_end=start - timedelta(days=1),
        days=days,
    )


# ── Marca ────────────────────────────────────────────────────────────


def normalize(value: str) -> str:
    """Sin acentos ni mayúsculas; lo que no es letra o número pasa a espacio."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in stripped).split())


def _compact(value: str) -> str:
    return value.replace(" ", "")


@dataclass
class BrandMatcher:
    """Coincidencia por subcadena (sin regex) con o sin espacios."""
    terms: list[str]
    _patterns: list[tuple[str, str]] = field(init=False)
    _seen: dict[str, bool] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        patterns = []
        for term in self.terms or []:
            norm = normalize(term)
            if len(_compact(norm)) >= MIN_TERM_LENGTH:
                patterns.append((norm, _compact(norm)))
        self._patterns = patterns

    def __call__(self, query: str) -> bool:
        if not self._patterns:
            return False
        hit = self._seen.get(query)
        if hit is None:
            norm = normalize(query)
            compact = _compact(norm)
            hit = any(p in norm or c in compact for p, c in self._patterns)
            self._seen[query] = hit
        return hit


def is_brand(query: str, terms: list[str]) -> bool:
    return BrandMatcher(list(terms))(query)


def clean_brand_terms(values: list | None) -> list[str]:
    """Valida lo que llega del editor: recorta, quita duplicados (tras
    normalizar) y exige 3–60 caracteres por término y como mucho 20."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        if not isinstance(raw, str):
            raise ValueError("Cada término de marca debe ser texto")
        term = " ".join(raw.split())
        if not term:
            continue
        if not MIN_TERM_LENGTH <= len(term) <= MAX_TERM_LENGTH:
            raise ValueError(
                f"Cada término de marca debe tener entre {MIN_TERM_LENGTH} y {MAX_TERM_LENGTH} caracteres"
            )
        key = _compact(normalize(term))
        if len(key) < MIN_TERM_LENGTH:
            raise ValueError(f"Cada término de marca necesita al menos {MIN_TERM_LENGTH} letras o números")
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    if len(out) > MAX_BRAND_TERMS:
        raise ValueError(f"Como mucho {MAX_BRAND_TERMS} términos de marca")
    return out


# ── Secciones ────────────────────────────────────────────────────────


def section_of(page_url: str, site_url: str | None) -> tuple[str, str]:
    """(clave, etiqueta) de la sección de una página: su primer tramo de ruta.

    - Sin query ni fragmento; el tramo se decodifica y pasa a minúsculas.
    - Un fichero suelto en la raíz (/contacto.html) es su propia sección.
    - Ruta vacía → ("/", "Inicio").
    - En propiedades de dominio, las páginas de otro subdominio (no el apex
      ni www) se agrupan por su host.
    - En propiedades de prefijo de URL, la ruta cuenta desde el prefijo.
    """
    parts = urlsplit(page_url or "")
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    site = site_url or ""
    if site.startswith("sc-domain:"):
        apex = site[len("sc-domain:"):].strip().strip("/").lower()
        if host and apex and host not in (apex, f"www.{apex}"):
            return host, host
    elif site:
        prefix = urlsplit(site)
        prefix_path = prefix.path or "/"
        if prefix_path != "/" and path.startswith(prefix_path):
            path = path[len(prefix_path) - 1:]
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "/", "Inicio"
    first = unquote(segments[0]).lower()
    return f"/{first}", f"/{first}"


# ── Cifras ───────────────────────────────────────────────────────────


@dataclass
class Agg:
    """Sumas de una consulta/página/clase en la ventana y en la anterior."""
    clicks: int = 0
    impressions: int = 0
    weighted: float = 0.0  # SUM(posición × impresiones)
    prev_clicks: int = 0
    prev_impressions: int = 0
    prev_weighted: float = 0.0

    def add(self, other: "Agg") -> None:
        self.clicks += other.clicks
        self.impressions += other.impressions
        self.weighted += other.weighted
        self.prev_clicks += other.prev_clicks
        self.prev_impressions += other.prev_impressions
        self.prev_weighted += other.prev_weighted


def weighted_position(weighted: float, impressions: int) -> float | None:
    return weighted / impressions if impressions > 0 else None


def position_delta(previous: float | None, current: float | None) -> float | None:
    """Positivo = mejora (se baja de la posición 8 a la 5 → +3)."""
    if previous is None or current is None:
        return None
    return round(previous - current, 2)


def pct_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) * 100 / previous, 1)


def mover_state(impressions: int, previous_impressions: int) -> str:
    """`new` sólo sale ahora; `lost` sólo salía antes; `both` en las dos."""
    if previous_impressions <= 0 and impressions > 0:
        return "new"
    if impressions <= 0 and previous_impressions > 0:
        return "lost"
    return "both"


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def mover_row(agg: Agg) -> dict:
    position = weighted_position(agg.weighted, agg.impressions)
    previous = weighted_position(agg.prev_weighted, agg.prev_impressions)
    return {
        "clicks": agg.clicks,
        "previous_clicks": agg.prev_clicks,
        "clicks_delta": agg.clicks - agg.prev_clicks,
        "clicks_pct": pct_change(agg.clicks, agg.prev_clicks),
        "impressions": agg.impressions,
        "previous_impressions": agg.prev_impressions,
        "position": _round(position),
        "previous_position": _round(previous),
        "position_delta": position_delta(previous, position),
        "state": mover_state(agg.impressions, agg.prev_impressions),
    }


def select_movers(rows: list[dict], sort: MoverSort, *, min_impressions: int = DEFAULT_MIN_IMPRESSIONS) -> list[dict]:
    """Filtra y ordena. Por clics: el umbral vale en la ventana con más
    impresiones (así salen las nuevas y las perdidas). Por posición: en las
    dos ventanas (una posición sobre 2 impresiones no dice nada)."""
    if sort in ("clicks_gain", "clicks_loss"):
        picked = [r for r in rows if max(r["impressions"], r["previous_impressions"]) >= min_impressions]
        if sort == "clicks_gain":
            picked = [r for r in picked if r["clicks_delta"] > 0]
            picked.sort(key=lambda r: (-r["clicks_delta"], -r["clicks"], r["key"]))
        else:
            picked = [r for r in picked if r["clicks_delta"] < 0]
            picked.sort(key=lambda r: (r["clicks_delta"], -r["previous_clicks"], r["key"]))
        return picked
    picked = [
        r for r in rows
        if r["impressions"] >= min_impressions and r["previous_impressions"] >= min_impressions
        and r["position_delta"] is not None
    ]
    if sort == "position_gain":
        picked = [r for r in picked if r["position_delta"] > 0]
        picked.sort(key=lambda r: (-r["position_delta"], -r["impressions"], r["key"]))
    else:
        picked = [r for r in picked if r["position_delta"] < 0]
        picked.sort(key=lambda r: (r["position_delta"], -r["impressions"], r["key"]))
    return picked


def unclassified(total: int, classified: int) -> int:
    """Lo que Google no atribuye a ninguna consulta. Nunca negativo."""
    return max(total - classified, 0)


# ── Estado de la propiedad ───────────────────────────────────────────


@dataclass(frozen=True)
class SeoSource:
    status: SeoStatus
    site_url: str | None
    error_code: str | None = None
    last_synced_at: datetime | None = None
    end: date | None = None
    # Cambia con cada pasada de los jobs: invalida la caché.
    version: tuple = ()


async def load_source(db, client: Client) -> SeoSource:
    site = normalize_site_url(client.gsc_url)
    if not site:
        return SeoSource("no_property", None)
    connections = dict((await db.execute(select(GscConnection.id, GscConnection.status))).all())
    sync = await db.get(GscSiteSync, site)
    detail = await db.get(GscDetailSync, site)
    error_code = (detail.error_code if detail else None) or (sync.error_code if sync else None)
    last_synced_at = detail.last_synced_at if detail else None

    if (sync and sync.backfilled_at and sync.last_data_date
            and detail and detail.backfilled_at and detail.last_data_date):
        end = min(sync.last_data_date, detail.last_data_date)
        version = (sync.last_synced_at, detail.last_synced_at, sync.last_data_date, detail.last_data_date)
        return SeoSource("ok", site, error_code, last_synced_at, end, version)

    def blocked(status: SeoStatus) -> SeoSource:
        return SeoSource(status, site, error_code, last_synced_at)

    if not connections:
        return blocked("not_connected")
    site_connection = connections.get(sync.connection_id) if sync and sync.connection_id else None
    if ("connected" not in connections.values() or site_connection == "reconnect_required"
            or error_code == "reconnect_required"):
        return blocked("reconnect_required")
    if detail is not None and detail.error_code and detail.error_code != "pending_access":
        return blocked("error")
    if sync is not None and sync.error_code and not sync.backfilled_at:
        return blocked("error")
    if detail is None or detail.error_code == "pending_access" or not (sync and sync.backfilled_at):
        return blocked("not_synced")
    return blocked("backfilling")


# ── Lecturas (una pasada por el rango de la PK) ──────────────────────

_DETAIL_SQL = {
    dimension: text(f"""
        SELECT {dimension} AS key,
          COALESCE(SUM(clicks) FILTER (WHERE date >= :start), 0) AS clicks,
          COALESCE(SUM(impressions) FILTER (WHERE date >= :start), 0) AS impressions,
          COALESCE(SUM(position::float8 * impressions) FILTER (WHERE date >= :start), 0) AS weighted,
          COALESCE(SUM(clicks) FILTER (WHERE date < :start), 0) AS prev_clicks,
          COALESCE(SUM(impressions) FILTER (WHERE date < :start), 0) AS prev_impressions,
          COALESCE(SUM(position::float8 * impressions) FILTER (WHERE date < :start), 0) AS prev_weighted
        FROM gsc_{dimension}_daily
        WHERE site_url = :site AND date >= :prev_start AND date <= :end
        GROUP BY {dimension}
    """)
    for dimension in ("query", "page")
}

_TOTALS_SQL = text("""
    SELECT
      COALESCE(SUM(clicks) FILTER (WHERE date >= :start), 0) AS clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date >= :start), 0) AS impressions,
      COALESCE(SUM(position * impressions) FILTER (WHERE date >= :start), 0) AS weighted,
      COALESCE(SUM(clicks) FILTER (WHERE date < :start), 0) AS prev_clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date < :start), 0) AS prev_impressions,
      COALESCE(SUM(position * impressions) FILTER (WHERE date < :start), 0) AS prev_weighted
    FROM gsc_daily
    WHERE site_url = :site AND date >= :prev_start AND date <= :end
""")

# Semana 0 = los 7 días que acaban en `end`; sólo filas con clics (el gráfico es de clics).
_TREND_QUERY_SQL = text("""
    SELECT query AS key, (CAST(:end AS date) - date) / 7 AS week, SUM(clicks) AS clicks
    FROM gsc_query_daily
    WHERE site_url = :site AND date > :floor AND date <= :end AND clicks > 0
    GROUP BY query, week
""")
_TREND_TOTAL_SQL = text("""
    SELECT (CAST(:end AS date) - date) / 7 AS week, SUM(clicks) AS clicks
    FROM gsc_daily
    WHERE site_url = :site AND date > :floor AND date <= :end
    GROUP BY week
""")

# Caché en proceso (1 h) de las agregaciones del detalle, por propiedad,
# ventana y pasada de los jobs. La marca se aplica después: no entra en la clave.
CACHE_SECONDS = 3600
_CACHE_MAX = 256
_cache: dict[tuple, tuple[float, object]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _cached(key: tuple, compute):
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = await compute()
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (now, value)
    return value


def _params(source: SeoSource, window: SeoWindow) -> dict:
    return {"site": source.site_url, "start": window.start, "prev_start": window.previous_start, "end": window.end}


def _agg(row) -> Agg:
    return Agg(int(row.clicks), int(row.impressions), float(row.weighted),
               int(row.prev_clicks), int(row.prev_impressions), float(row.prev_weighted))


async def detail_aggregates(db, source: SeoSource, window: SeoWindow, dimension: str) -> dict[str, Agg]:
    async def compute():
        rows = (await db.execute(_DETAIL_SQL[dimension], _params(source, window))).all()
        return {row.key: _agg(row) for row in rows}
    return await _cached((dimension, source.site_url, window.end, window.days, source.version), compute)


async def property_totals(db, source: SeoSource, window: SeoWindow) -> Agg:
    return _agg((await db.execute(_TOTALS_SQL, _params(source, window))).one())


async def _trend_rows(db, source: SeoSource, end: date):
    async def compute():
        params = {"site": source.site_url, "end": end, "floor": end - timedelta(days=7 * TREND_WEEKS)}
        queries = [(r.key, int(r.week), int(r.clicks)) for r in (await db.execute(_TREND_QUERY_SQL, params)).all()]
        totals = {int(r.week): int(r.clicks) for r in (await db.execute(_TREND_TOTAL_SQL, params)).all()}
        return queries, totals
    return await _cached(("trend", source.site_url, end, source.version), compute)


# ── Respuestas ───────────────────────────────────────────────────────


def _totals_block(agg: Agg) -> dict:
    def side(clicks, impressions, weighted):
        position = weighted_position(weighted, impressions)
        return {
            "clicks": clicks, "impressions": impressions,
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": _round(position),
        }
    current = side(agg.clicks, agg.impressions, agg.weighted)
    previous = side(agg.prev_clicks, agg.prev_impressions, agg.prev_weighted)
    ctr_delta = (round(current["ctr"] - previous["ctr"], 4)
                 if current["ctr"] is not None and previous["ctr"] is not None else None)
    return {
        "current": current,
        "previous": previous,
        "change": {
            "clicks_pct": pct_change(agg.clicks, agg.prev_clicks),
            "impressions_pct": pct_change(agg.impressions, agg.prev_impressions),
            "ctr_delta": ctr_delta,
            "position_delta": position_delta(
                weighted_position(agg.prev_weighted, agg.prev_impressions),
                weighted_position(agg.weighted, agg.impressions),
            ),
        },
    }


def _brand_split(totals: Agg, queries: dict[str, Agg], matcher: BrandMatcher) -> tuple[dict, dict]:
    brand, non_brand = Agg(), Agg()
    for query, agg in queries.items():
        (brand if matcher(query) else non_brand).add(agg)
    classified_clicks = brand.clicks + non_brand.clicks
    classified_impressions = brand.impressions + non_brand.impressions
    prev_classified_clicks = brand.prev_clicks + non_brand.prev_clicks
    prev_classified_impressions = brand.prev_impressions + non_brand.prev_impressions
    current = {
        "brand": {"clicks": brand.clicks, "impressions": brand.impressions},
        "non_brand": {"clicks": non_brand.clicks, "impressions": non_brand.impressions},
        "unclassified": {
            "clicks": unclassified(totals.clicks, classified_clicks),
            "impressions": unclassified(totals.impressions, classified_impressions),
        },
    }
    previous = {
        "brand": {"clicks": brand.prev_clicks, "impressions": brand.prev_impressions},
        "non_brand": {"clicks": non_brand.prev_clicks, "impressions": non_brand.prev_impressions},
        "unclassified": {
            "clicks": unclassified(totals.prev_clicks, prev_classified_clicks),
            "impressions": unclassified(totals.prev_impressions, prev_classified_impressions),
        },
    }
    return current, previous


def _trend(end: date, query_weeks, total_weeks: dict[int, int], matcher: BrandMatcher) -> list[dict]:
    brand = [0] * TREND_WEEKS
    non_brand = [0] * TREND_WEEKS
    for query, week, clicks in query_weeks:
        if 0 <= week < TREND_WEEKS:
            if matcher(query):
                brand[week] += clicks
            else:
                non_brand[week] += clicks
    out = []
    for week in reversed(range(TREND_WEEKS)):
        week_end = end - timedelta(days=7 * week)
        out.append({
            "week_start": (week_end - timedelta(days=6)).isoformat(),
            "week_end": week_end.isoformat(),
            "brand_clicks": brand[week],
            "non_brand_clicks": non_brand[week],
            "unclassified_clicks": unclassified(total_weeks.get(week, 0), brand[week] + non_brand[week]),
        })
    return out


def _sections(pages: dict[str, Agg], site_url: str) -> list[dict]:
    groups: dict[str, tuple[str, Agg, int]] = {}
    for page, agg in pages.items():
        key, label = section_of(page, site_url)
        _, total, count = groups.get(key, (label, Agg(), 0))
        total.add(agg)
        groups[key] = (label, total, count + (1 if agg.impressions > 0 else 0))
    all_clicks = sum(agg.clicks for _, agg, _ in groups.values())
    out = []
    for key, (label, agg, count) in groups.items():
        if agg.impressions <= 0 and agg.prev_impressions <= 0:
            continue
        position = weighted_position(agg.weighted, agg.impressions)
        previous = weighted_position(agg.prev_weighted, agg.prev_impressions)
        out.append({
            "key": key,
            "label": label,
            "clicks": agg.clicks,
            "previous_clicks": agg.prev_clicks,
            "clicks_pct": pct_change(agg.clicks, agg.prev_clicks),
            # Reparto por clics: las impresiones por página no suman el total.
            "clicks_share": round(agg.clicks / all_clicks, 4) if all_clicks else None,
            "impressions": agg.impressions,
            "position": _round(position),
            "position_delta": position_delta(previous, position),
            "pages": count,
        })
    out.sort(key=lambda s: (-s["clicks"], -s["impressions"], s["key"]))
    return out


def _query_rows(queries: dict[str, Agg], matcher: BrandMatcher) -> list[dict]:
    return [{"key": q, "query": q, "is_brand": matcher(q), **mover_row(a)} for q, a in queries.items()]


def _page_rows(pages: dict[str, Agg], site_url: str) -> list[dict]:
    rows = []
    for page, agg in pages.items():
        key, label = section_of(page, site_url)
        rows.append({"key": page, "page": page, "section": key, "section_label": label, **mover_row(agg)})
    return rows


def _public(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "key"} for r in rows]


def _blocked_payload(source: SeoSource) -> dict:
    return {
        "status": source.status,
        "site_url": source.site_url,
        "error_code": source.error_code,
        "last_synced_at": source.last_synced_at,
    }


async def summary(db, client: Client, *, days: int = SEO_WINDOW_DAYS) -> dict:
    source = await load_source(db, client)
    if source.status != "ok":
        return {**_blocked_payload(source), "window": None, "totals": None, "brand": None,
                "sections": [], "queries": None, "pages": None, "coverage": None}
    window = seo_window(source.end, days)
    totals = await property_totals(db, source, window)
    queries = await detail_aggregates(db, source, window, "query")
    pages = await detail_aggregates(db, source, window, "page")
    matcher = BrandMatcher(list(client.brand_terms or []))
    current, previous = _brand_split(totals, queries, matcher)
    trend_queries, trend_totals = await _trend_rows(db, source, source.end)

    query_rows = _query_rows(queries, matcher)
    page_rows = _page_rows(pages, source.site_url)
    query_clicks = sum(a.clicks for a in queries.values())
    return {
        **_blocked_payload(source),
        "window": window.as_dict(),
        "totals": _totals_block(totals),
        "brand": {
            "terms": list(client.brand_terms or []),
            "current": current,
            "previous": previous,
            "trend": _trend(source.end, trend_queries, trend_totals, matcher),
        },
        "sections": _sections(pages, source.site_url),
        "queries": {
            "gainers": _public(select_movers(query_rows, "clicks_gain")[:MOVERS_IN_SUMMARY]),
            "losers": _public(select_movers(query_rows, "clicks_loss")[:MOVERS_IN_SUMMARY]),
        },
        "pages": {
            "gainers": _public(select_movers(page_rows, "clicks_gain")[:MOVERS_IN_SUMMARY]),
            "losers": _public(select_movers(page_rows, "clicks_loss")[:MOVERS_IN_SUMMARY]),
        },
        "coverage": {
            "query_clicks_share": round(min(query_clicks / totals.clicks, 1.0), 4) if totals.clicks else None,
        },
    }


async def movers(
    db, client: Client, dimension: Literal["query", "page"], *,
    days: int = SEO_WINDOW_DAYS, sort: MoverSort = "clicks_gain", brand: BrandFilter = "all",
    q: str | None = None, min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
    limit: int = 25, section: str | None = None,
) -> dict:
    """Lista completa (paginada por `limit`) de consultas o páginas que se mueven."""
    source = await load_source(db, client)
    if source.status != "ok":
        return {**_blocked_payload(source), "window": None, "rows": [], "total": 0}
    window = seo_window(source.end, days)
    aggregates = await detail_aggregates(db, source, window, dimension)
    if dimension == "query":
        rows = _query_rows(aggregates, BrandMatcher(list(client.brand_terms or [])))
        if brand != "all":
            wanted = brand == "brand"
            rows = [r for r in rows if r["is_brand"] is wanted]
    else:
        rows = _page_rows(aggregates, source.site_url)
        if section:
            rows = [r for r in rows if r["section"] == section]
    needle = normalize(q or "")
    if needle:
        rows = [r for r in rows if needle in normalize(r["key"])]
    picked = select_movers(rows, sort, min_impressions=min_impressions)
    return {
        **_blocked_payload(source),
        "window": window.as_dict(),
        "rows": _public(picked[:min(limit, MAX_LIMIT)]),
        "total": len(picked),
    }
