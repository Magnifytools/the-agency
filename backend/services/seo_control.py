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

Historial por consulta: los meses de `gsc_query_monthly` (hasta 16, sólo
completos, más los anteriores importados de The Engine) más los días del
detalle diario (120). Grupos de URL: reglas
propias del cliente (`clients.seo_page_groups`); cada página va al PRIMER
grupo que la acepta y, si ninguno, a "Sin grupo".

Dos trampas del detalle:
- Google anonimiza las consultas poco frecuentes: "sin clasificar" = total de
  `gsc_daily` − suma de consultas (nunca por debajo de 0).
- Las impresiones por página no suman el total de la propiedad (una búsqueda
  que enseña dos páginas cuenta en las dos). Por eso las secciones se reparten
  por clics y sus impresiones sólo se enseñan en absoluto.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import unquote, urlsplit

from sqlalchemy import select, text

from backend.db.models import Client, GscConnection, GscDetailSync, GscSiteSync
from backend.services.gsc_detail_service import DETAIL_DAYS, history_floor
from backend.services.gsc_service import normalize_site_url

try:  # Python ≥ 3.11
    from re import _parser as _sre_parse
except ImportError:  # pragma: no cover
    import sre_parse as _sre_parse  # type: ignore[no-redef]

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

# Historial por consulta: meses de la miniatura de tendencia en los listados.
TREND_MONTHS = 6

# Grupos de URL.
MAX_PAGE_GROUPS = 30
MAX_GROUP_RULES = 20
MAX_GROUP_NAME = 60
MAX_RULE_VALUE = 200
RULE_TYPES = ("prefix", "contains", "regex")
UNGROUPED = "Sin grupo"
# Repeticiones sin tope (*, +, {n,}) que admite una regex.
MAX_REGEX_UNBOUNDED = 2
# Tope de tiempo para repartir las páginas entre grupos (ver PageGroupMatcher).
GROUP_MATCH_SECONDS = 5.0

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


# ── Grupos de URL ────────────────────────────────────────────────────
#
# Cada grupo: {"name", "rules": [{"type": "prefix"|"contains"|"regex", "value"}]}.
# - prefix: la RUTA empieza por el valor ("/blog/"; sin barra inicial se le
#   pone). La ruta es como en las secciones: decodificada, en minúsculas, con
#   su ?query y, en propiedades de prefijo, contada desde el prefijo. Si el
#   valor es una URL entera (http…), se compara con la URL entera.
# - contains: el valor aparece en cualquier parte de la URL entera
#   (decodificada, sin mayúsculas): sirve también para subdominios.
# - regex: `re.search` sobre la ruta, sin distinguir mayúsculas.
#
# Regex segura sin timeout: `re` de Python no tiene tope de tiempo, así que se
# validan al guardar: ≤ 200 caracteres, sin repeticiones anidadas ((a+)+),
# sin alternativas dentro de una repetición sin tope ((a|ab)*), sin
# referencias hacia atrás ni lookarounds y como mucho 2 repeticiones sin tope.
# Eso deja fuera el retroceso exponencial; lo polinómico queda acotado porque
# la ruta es corta (la URL se guarda recortada a 2.000 caracteres). Además el
# reparto entero tiene un tope de 5 s (`PageGroupTimeout`).


class PageGroupTimeout(Exception):
    """Las reglas tardan demasiado en repartir las páginas."""


_REPEATS = {getattr(_sre_parse, name) for name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT")
            if hasattr(_sre_parse, name)}
_LOOKAROUNDS = {_sre_parse.ASSERT, _sre_parse.ASSERT_NOT}
_BACKREFS = {_sre_parse.GROUPREF, _sre_parse.GROUPREF_EXISTS}
# A partir de aquí una repetición cuenta como "sin tope".
_LARGE_REPEAT = 100


def regex_problem(pattern: str) -> str | None:
    """Motivo por el que una regex no se admite, o None si vale."""
    if len(pattern) > MAX_RULE_VALUE:
        return f"tiene más de {MAX_RULE_VALUE} caracteres"
    try:
        re.compile(pattern, re.IGNORECASE)
        parsed = _sre_parse.parse(pattern)
    except re.error:
        return "no es una expresión regular válida"
    unbounded = 0

    def children(op, av) -> list:
        if op in _REPEATS:
            return [av[2]]
        if op is _sre_parse.SUBPATTERN:
            return [av[-1]]
        if op is _sre_parse.BRANCH:
            return list(av[1])
        if op is getattr(_sre_parse, "ATOMIC_GROUP", None):
            return [av]
        return []

    def walk(items, repeat_depth: int, in_unbounded: bool) -> str | None:
        nonlocal unbounded
        for op, av in items:
            if op in _BACKREFS:
                return "no admite referencias hacia atrás (\\1)"
            if op in _LOOKAROUNDS:
                return "no admite lookarounds ((?=…), (?!…), (?<=…))"
            if op is _sre_parse.BRANCH and in_unbounded:
                return "no admite alternativas (a|b) dentro de una repetición sin tope"
            if op in _REPEATS:
                low, high, _ = av
                if high > 1 and repeat_depth > 0:
                    return "no admite repeticiones anidadas como (a+)+"
                is_unbounded = high == _sre_parse.MAXREPEAT or high > _LARGE_REPEAT
                if is_unbounded:
                    unbounded += 1
                for child in children(op, av):
                    problem = walk(child, repeat_depth + (1 if high > 1 else 0), in_unbounded or is_unbounded)
                    if problem:
                        return problem
                continue
            for child in children(op, av):
                problem = walk(child, repeat_depth, in_unbounded)
                if problem:
                    return problem
        return None

    problem = walk(parsed, 0, False)
    if problem:
        return problem
    if unbounded > MAX_REGEX_UNBOUNDED:
        return f"tiene más de {MAX_REGEX_UNBOUNDED} repeticiones sin tope (*, +)"
    return None


def clean_page_groups(values: list | None) -> list[dict]:
    """Valida los grupos que llegan del editor: como mucho 30 grupos de 20
    reglas, nombres de 1–60 caracteres sin repetir (ni "Sin grupo"), valores
    de 1–200 caracteres y regex seguras (`regex_problem`)."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("Los grupos de URL son una lista")
    if len(values) > MAX_PAGE_GROUPS:
        raise ValueError(f"Como mucho {MAX_PAGE_GROUPS} grupos de URL")
    out: list[dict] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise ValueError("Cada grupo necesita un nombre y sus reglas")
        name = " ".join(raw["name"].split())
        if not 1 <= len(name) <= MAX_GROUP_NAME:
            raise ValueError(f"El nombre de cada grupo debe tener entre 1 y {MAX_GROUP_NAME} caracteres")
        key = name.casefold()
        if key == UNGROUPED.casefold():
            raise ValueError(f"«{UNGROUPED}» está reservado para las páginas que no entran en ningún grupo")
        if key in seen:
            raise ValueError(f"Hay dos grupos llamados «{name}»")
        seen.add(key)
        rules = raw.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValueError(f"El grupo «{name}» necesita al menos una regla")
        if len(rules) > MAX_GROUP_RULES:
            raise ValueError(f"El grupo «{name}» tiene más de {MAX_GROUP_RULES} reglas")
        clean_rules = []
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") not in RULE_TYPES or not isinstance(rule.get("value"), str):
                raise ValueError(f"Regla no válida en «{name}»: el tipo es prefix, contains o regex, con su valor")
            value = rule["value"].strip()
            if not 1 <= len(value) <= MAX_RULE_VALUE:
                raise ValueError(f"Cada regla de «{name}» debe tener entre 1 y {MAX_RULE_VALUE} caracteres")
            if rule["type"] == "regex":
                problem = regex_problem(value)
                if problem:
                    raise ValueError(f"La regex «{value}» de «{name}» {problem}")
            clean_rules.append({"type": rule["type"], "value": value})
        out.append({"name": name, "rules": clean_rules})
    return out


def page_path(page_url: str, site_url: str | None) -> str:
    """Ruta de la página para las reglas: decodificada, en minúsculas, con su
    ?query; en propiedades de prefijo, desde el prefijo (como las secciones)."""
    parts = urlsplit(page_url or "")
    path = parts.path or "/"
    site = site_url or ""
    if site and not site.startswith("sc-domain:"):
        prefix_path = urlsplit(site).path or "/"
        if prefix_path != "/" and path.startswith(prefix_path):
            path = path[len(prefix_path) - 1:]
    if parts.query:
        path = f"{path}?{parts.query}"
    return unquote(path).lower()


def _compile_rule(rule: dict):
    kind, value = rule.get("type"), str(rule.get("value") or "")
    if kind == "prefix":
        lowered = unquote(value).lower()
        if lowered.startswith(("http://", "https://")):
            return lambda path, url: url.startswith(lowered)
        if not lowered.startswith("/"):
            lowered = f"/{lowered}"
        return lambda path, url: path.startswith(lowered)
    if kind == "contains":
        lowered = unquote(value).lower()
        return lambda path, url: lowered in url
    if kind == "regex" and regex_problem(value) is None:
        pattern = re.compile(value, re.IGNORECASE)
        return lambda path, url: pattern.search(path) is not None
    return None  # regla vieja o rota: no acepta nada


class PageGroupMatcher:
    """Grupo de cada página: el PRIMERO (en el orden guardado) con alguna
    regla que la acepte; si ninguno, "Sin grupo". Recuerda lo ya resuelto."""

    def __init__(self, groups: list | None, site_url: str | None):
        self.site_url = site_url
        self.names: list[str] = []
        self._groups: list[tuple[str, list]] = []
        for group in groups or []:
            if not isinstance(group, dict) or not group.get("name"):
                continue
            rules = [r for r in (_compile_rule(rule) for rule in group.get("rules") or [] if isinstance(rule, dict)) if r]
            self.names.append(group["name"])
            self._groups.append((group["name"], rules))
        self._seen: dict[str, str] = {}

    def __call__(self, page_url: str) -> str:
        name = self._seen.get(page_url)
        if name is None:
            name = UNGROUPED
            if self._groups:
                path = page_path(page_url, self.site_url)
                url = unquote(page_url or "").lower()
                for group_name, rules in self._groups:
                    if any(rule(path, url) for rule in rules):
                        name = group_name
                        break
            self._seen[page_url] = name
        return name

    def assign(self, pages, *, budget_seconds: float = GROUP_MATCH_SECONDS) -> dict[str, str]:
        """Grupo de cada página, con tope de tiempo para todo el reparto."""
        deadline = time.monotonic() + budget_seconds
        out = {}
        for i, page in enumerate(pages):
            if i % 200 == 0 and time.monotonic() > deadline:
                raise PageGroupTimeout()
            out[page] = self(page)
        return out


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


def _agg(row) -> Agg:
    return Agg(int(row.clicks), int(row.impressions), float(row.weighted),
               int(row.prev_clicks), int(row.prev_impressions), float(row.prev_weighted))


async def range_aggregates(db, site: str, *, start: date, previous_start: date, end: date,
                           dimension: str) -> dict[str, Agg]:
    """Sumas por consulta o página de [start, end] y de [previous_start, start).
    Sin caché: también la usa el resumen mensual, cuyos meses no son la ventana
    de 28 días (un febrero tendría la misma clave de caché que esa ventana)."""
    params = {"site": site, "start": start, "prev_start": previous_start, "end": end}
    rows = (await db.execute(_DETAIL_SQL[dimension], params)).all()
    return {row.key: _agg(row) for row in rows}


async def range_totals(db, site: str, *, start: date, previous_start: date, end: date) -> Agg:
    """Totales de `gsc_daily` con los mismos tramos que `range_aggregates`."""
    params = {"site": site, "start": start, "prev_start": previous_start, "end": end}
    return _agg((await db.execute(_TOTALS_SQL, params)).one())


async def detail_aggregates(db, source: SeoSource, window: SeoWindow, dimension: str) -> dict[str, Agg]:
    async def compute():
        return await range_aggregates(db, source.site_url, start=window.start,
                                      previous_start=window.previous_start, end=window.end,
                                      dimension=dimension)
    return await _cached((dimension, source.site_url, window.end, window.days, source.version), compute)


async def property_totals(db, source: SeoSource, window: SeoWindow) -> Agg:
    return await range_totals(db, source.site_url, start=window.start,
                              previous_start=window.previous_start, end=window.end)


async def _trend_rows(db, source: SeoSource, end: date):
    async def compute():
        params = {"site": source.site_url, "end": end, "floor": end - timedelta(days=7 * TREND_WEEKS)}
        queries = [(r.key, int(r.week), int(r.clicks)) for r in (await db.execute(_TREND_QUERY_SQL, params)).all()]
        totals = {int(r.week): int(r.clicks) for r in (await db.execute(_TREND_TOTAL_SQL, params)).all()}
        return queries, totals
    return await _cached(("trend", source.site_url, end, source.version), compute)


# ── Historial por consulta (meses + días) ────────────────────────────

# Meses con datos de la propiedad (una búsqueda por mes, con la PK).
_SITE_MONTHS_SQL = text("""
    SELECT CAST(m AS date) AS month
    FROM generate_series(CAST(:floor AS date), CAST(:last AS date), interval '1 month') AS m
    WHERE EXISTS (
        SELECT 1 FROM gsc_query_monthly g WHERE g.site_url = :site AND g.month = CAST(m AS date)
    )
    ORDER BY 1
""")
_HISTORY_MONTHS_SQL = text("""
    SELECT month, clicks, impressions, weighted_position_sum AS weighted
    FROM gsc_query_monthly
    WHERE site_url = :site AND query = :query AND month >= :floor
""")
_HISTORY_DAYS_SQL = text("""
    SELECT date, clicks, impressions, position
    FROM gsc_query_daily
    WHERE site_url = :site AND query = :query AND date >= :start AND date <= :end
""")
_IMPORTED_MONTHS_SQL = text("""
    SELECT DISTINCT month FROM gsc_query_monthly
    WHERE site_url = :site AND source = 'engine' AND month >= :floor
""")
_FIRST_DAY_SQL = text("SELECT MIN(date) FROM gsc_query_daily WHERE site_url = :site")
_TREND_MONTHLY_SQL = text("""
    SELECT query, month, impressions, weighted_position_sum AS weighted
    FROM gsc_query_monthly
    WHERE site_url = :site AND query = ANY(CAST(:queries AS text[])) AND month >= :first
""")


_IMPORTED_FLOOR_SQL = text("""
    SELECT MIN(month) FROM gsc_query_monthly WHERE site_url = :site AND source = 'engine'
""")


async def _site_months(db, source: SeoSource) -> list[date]:
    """Meses completos guardados de la propiedad dentro de los 16 del historial,
    más los anteriores importados de The Engine (no caducan)."""
    async def compute():
        floor = history_floor(source.end)
        imported = await db.scalar(_IMPORTED_FLOOR_SQL, {"site": source.site_url})
        params = {"site": source.site_url, "floor": min(floor, imported) if imported else floor,
                  "last": source.end.replace(day=1)}
        return [r.month for r in (await db.execute(_SITE_MONTHS_SQL, params)).all()]
    return await _cached(("months", source.site_url, source.end, source.version), compute)


def _point(clicks: int, impressions: int, weighted: float) -> dict:
    return {"clicks": int(clicks), "impressions": int(impressions),
            "position": _round(weighted_position(float(weighted), int(impressions)))}


async def _attach_trends(db, source: SeoSource, rows: list[dict]) -> list[str]:
    """Añade a cada consulta `trend`: su posición en los últimos 6 meses
    guardados (None si ese mes no salió). Devuelve esos meses."""
    months = (await _site_months(db, source))[-TREND_MONTHS:]
    if not months or not rows:
        for row in rows:
            row["trend"] = []
        return [m.isoformat() for m in months]
    found: dict[tuple[str, date], float | None] = {}
    params = {"site": source.site_url, "queries": [r["query"] for r in rows], "first": months[0]}
    for r in (await db.execute(_TREND_MONTHLY_SQL, params)).all():
        found[(r.query, r.month)] = _round(weighted_position(float(r.weighted), int(r.impressions)))
    for row in rows:
        row["trend"] = [found.get((row["query"], m)) for m in months]
    return [m.isoformat() for m in months]


async def query_history(db, client: Client, query: str) -> dict:
    """Historial de una consulta: un punto por mes guardado (hasta 16, sólo
    completos) y uno por día del detalle (hasta 120, días sin fila = 0 clics
    y sin posición). Posición ponderada por impresiones."""
    source = await load_source(db, client)
    if source.status != "ok":
        return {**_blocked_payload(source), "query": query, "is_brand": None,
                "months": [], "days": [], "monthly_backfilled": False}
    site = source.site_url
    site_months = await _site_months(db, source)
    floor = min([history_floor(source.end), *site_months[:1]])
    monthly = {r.month: r for r in (await db.execute(
        _HISTORY_MONTHS_SQL, {"site": site, "query": query, "floor": floor})).all()}
    # Meses de la web que sólo existen importados de The Engine (antes de los de Google).
    imported = set((await db.execute(_IMPORTED_MONTHS_SQL, {"site": site, "floor": floor})).scalars().all())
    months = [
        {"month": m.isoformat(), **(_point(monthly[m].clicks, monthly[m].impressions, monthly[m].weighted)
                                    if m in monthly else _point(0, 0, 0.0)),
         "imported": m in imported}
        for m in site_months
    ]

    first_day = await db.scalar(_FIRST_DAY_SQL, {"site": site})
    start = source.end - timedelta(days=DETAIL_DAYS - 1)
    if first_day is not None:
        start = max(start, first_day)
    daily = {r.date: r for r in (await db.execute(
        _HISTORY_DAYS_SQL, {"site": site, "query": query, "start": start, "end": source.end})).all()}
    days = []
    day = start
    while day <= source.end:
        r = daily.get(day)
        days.append({"date": day.isoformat(), **(
            _point(r.clicks, r.impressions, float(r.position) * r.impressions) if r else _point(0, 0, 0.0))})
        day += timedelta(days=1)

    detail = await db.get(GscDetailSync, site)
    return {
        **_blocked_payload(source),
        "query": query,
        "is_brand": BrandMatcher(list(client.brand_terms or []))(query),
        "months": months,
        "days": days,
        # False mientras no se hayan traído de Google los meses de antes de los 120 días.
        "monthly_backfilled": bool(detail and detail.monthly_backfilled_at),
    }


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
    out = [
        _bucket_row(key, label, agg, count, all_clicks)
        for key, (label, agg, count) in groups.items()
        if agg.impressions > 0 or agg.prev_impressions > 0
    ]
    out.sort(key=lambda s: (-s["clicks"], -s["impressions"], s["key"]))
    return out


def _bucket_row(key: str, label: str, agg: Agg, pages: int, all_clicks: int) -> dict:
    """Fila de una sección o grupo de páginas."""
    position = weighted_position(agg.weighted, agg.impressions)
    previous = weighted_position(agg.prev_weighted, agg.prev_impressions)
    return {
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
        "pages": pages,
    }


def group_rows(pages: dict[str, Agg], matcher: PageGroupMatcher) -> list[dict]:
    """Cifras por grupo de URL, en el orden guardado (también los que no
    recogen ninguna página) y "Sin grupo" al final si tiene algo.

    Como las secciones: clics e impresiones sumados, posición ponderada y
    reparto por clics. "Páginas" = las que tienen impresiones en la ventana.
    """
    assigned = matcher.assign(list(pages))
    buckets: dict[str, list] = {name: [Agg(), 0] for name in [*matcher.names, UNGROUPED]}
    for page, agg in pages.items():
        bucket = buckets[assigned[page]]
        bucket[0].add(agg)
        bucket[1] += 1 if agg.impressions > 0 else 0
    all_clicks = sum(agg.clicks for agg in pages.values())
    out = [_bucket_row(name, name, *buckets[name], all_clicks) for name in matcher.names]
    ungrouped, count = buckets[UNGROUPED]
    if ungrouped.impressions > 0 or ungrouped.prev_impressions > 0:
        out.append(_bucket_row(UNGROUPED, UNGROUPED, ungrouped, count, all_clicks))
    return out


def _query_rows(queries: dict[str, Agg], matcher: BrandMatcher) -> list[dict]:
    return [{"key": q, "query": q, "is_brand": matcher(q), **mover_row(a)} for q, a in queries.items()]


def _page_rows(pages: dict[str, Agg], site_url: str, groups: PageGroupMatcher | None = None) -> list[dict]:
    rows = []
    for page, agg in pages.items():
        key, label = section_of(page, site_url)
        row = {"key": page, "page": page, "section": key, "section_label": label, **mover_row(agg)}
        if groups is not None:
            row["group"] = groups(page)
        rows.append(row)
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
    query_gainers = _public(select_movers(query_rows, "clicks_gain")[:MOVERS_IN_SUMMARY])
    query_losers = _public(select_movers(query_rows, "clicks_loss")[:MOVERS_IN_SUMMARY])
    trend_months = await _attach_trends(db, source, query_gainers + query_losers)
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
        "queries": {"gainers": query_gainers, "losers": query_losers, "trend_months": trend_months},
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
    limit: int = 25, section: str | None = None, group: str | None = None,
) -> dict:
    """Lista completa (paginada por `limit`) de consultas o páginas que se mueven.

    Las consultas llevan `trend` (posición de los últimos 6 meses guardados,
    `trend_months`); las páginas, su grupo de URL (`group`).
    """
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
        groups = PageGroupMatcher(client.seo_page_groups, source.site_url)
        groups.assign(list(aggregates))  # con tope de tiempo; luego sale de la memoria
        rows = _page_rows(aggregates, source.site_url, groups)
        if section:
            rows = [r for r in rows if r["section"] == section]
        if group:
            rows = [r for r in rows if r["group"] == group]
    needle = normalize(q or "")
    if needle:
        rows = [r for r in rows if needle in normalize(r["key"])]
    picked = select_movers(rows, sort, min_impressions=min_impressions)
    page = _public(picked[:min(limit, MAX_LIMIT)])
    out = {
        **_blocked_payload(source),
        "window": window.as_dict(),
        "rows": page,
        "total": len(picked),
    }
    if dimension == "query":
        out["trend_months"] = await _attach_trends(db, source, page)
    return out


async def page_groups(db, client: Client, *, days: int = SEO_WINDOW_DAYS, groups: list | None = None) -> dict:
    """Cifras por grupo de URL en la ventana y la anterior.

    `groups` permite probar unos grupos sin guardarlos (editor); si no llega,
    se usan los del cliente.
    """
    configured = client.seo_page_groups if groups is None else groups
    source = await load_source(db, client)
    if source.status != "ok":
        return {**_blocked_payload(source), "window": None, "groups": [], "configured": len(configured or [])}
    window = seo_window(source.end, days)
    pages = await detail_aggregates(db, source, window, "page")
    matcher = PageGroupMatcher(configured, source.site_url)
    return {
        **_blocked_payload(source),
        "window": window.as_dict(),
        "groups": group_rows(pages, matcher),
        "configured": len(matcher.names),
    }
