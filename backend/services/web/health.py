"""Salud diaria de las webs de los clientes (job ``web_health``, lock 18).

Dos comprobaciones diarias, cada una detrás del interruptor de la parte de Webs
de la que cuelga:

- **Caducidad** (con ``UPTIME_ENABLED``): por cada host de las URLs de
  disponibilidad activas de clientes activos y externos, cuándo caduca el
  certificado TLS (``safe_http.fetch_tls_certificate``: mismas garantías que un
  GET) y cuándo caduca el dominio registrable (RDAP).
- **robots.txt y sitemap** (con ``WEB_SWEEP_ENABLED``): por cada origen de las
  URLs vigiladas de clientes con la vigilancia de cambios encendida, el
  robots.txt (hash + cuerpo acotado, cambios y bloqueo total) y si el sitemap
  declarado (o ``/sitemap.xml``) responde y trae URLs.

RDAP: se usa el registro de servidores de la IANA (``dns.json``) y se pregunta
directamente al registro de cada TLD. Un TLD que no publica RDAP (``.es`` hoy)
queda como ``unsupported``: no hay fecha que leer y la ficha lo dice, en vez de
inventar una caducidad. El dominio registrable se busca preguntando del nombre
más largo al más corto (``www.`` fuera): el primero que el registro conoce.

La red va sin transacción abierta; luego se escribe todo de una vez. Las filas
de hosts u orígenes que ya no se miran se borran en la misma pasada: no queda
nada que no tenga un flujo que lo lea.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select

from backend.config import settings
from backend.db.models import (
    Client, ClientWebSettings, WebHostExpiry, WebRobotsState, WebUptimeTarget, WebWatch,
)
from backend.services.web.safe_http import (
    SSRFError, FetchResult, TlsCertificate, check_url_syntax, fetch, fetch_tls_certificate,
)
from backend.services.web.sitemap import fetch_sitemap_urls
from backend.services.web.sweep import decode_body, monitored_clients_clause, watched_clause
from backend.services.web.uptime import cause_label, monitored_clause

logger = logging.getLogger(__name__)

# Umbrales de aviso (días hasta caducar). Por debajo de "crítico", incidencia crítica.
CERT_WARNING_DAYS = 14
CERT_CRITICAL_DAYS = 3
DOMAIN_WARNING_DAYS = 30
DOMAIN_CRITICAL_DAYS = 7

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
RDAP_ACCEPT = "application/rdap+json, application/json;q=0.9"
_RDAP_MAX_BYTES = 256 * 1024
_BOOTSTRAP_MAX_BYTES = 1024 * 1024
_RDAP_MAX_CANDIDATES = 4
_RDAP_TIMEOUT_S = 15.0
_TLS_TIMEOUT_S = 10.0

# robots.txt: Google lee hasta 500 KiB; se guarda el cuerpo hasta 64 KiB.
ROBOTS_MAX_BYTES = 512 * 1024
ROBOTS_STORED_CHARS = 64 * 1024
_ROBOTS_TIMEOUT_S = 15.0
SITEMAP_URL_LIMIT = 1000
_SITEMAP_TIMEOUT_S = 60.0
MAX_ORIGINS_PER_CLIENT = 5
MAX_CONCURRENCY = 8


def level(days: int | None, warning: int, critical: int) -> str | None:
    """``critical`` / ``warning`` / ``ok`` según los días que quedan (None = sin fecha)."""
    if days is None:
        return None
    if days <= critical:
        return "critical"
    if days <= warning:
        return "warning"
    return "ok"


def days_left(expires_at: datetime | None, now: datetime) -> int | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return (expires_at - now).days  # timedelta.days redondea hacia abajo: caducado = negativo


# ── robots.txt ───────────────────────────────────────────────────────

_LINE = re.compile(r"^\s*([A-Za-z-]+)\s*:\s*(.*?)\s*$")


def parse_robots(body: str) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """(reglas por user-agent en minúsculas, sitemaps declarados).

    Grupos como los entiende Google: varias líneas ``User-agent`` seguidas
    comparten las reglas que vienen detrás; los comentarios (``#``) se quitan.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    sitemaps: list[str] = []
    current: list[str] = []
    in_rules = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0]
        match = _LINE.match(line)
        if not match:
            continue
        key, value = match.group(1).lower(), match.group(2)
        if key == "sitemap":
            if value:
                sitemaps.append(value)
            continue
        if key == "user-agent":
            if in_rules:
                current, in_rules = [], False
            agent = value.lower()
            current.append(agent)
            groups.setdefault(agent, [])
            continue
        if key in ("allow", "disallow") and current:
            in_rules = True
            for agent in current:
                groups[agent].append((key, value))
    return groups, sitemaps


def _group_blocks_all(rules: list[tuple[str, str]]) -> bool:
    disallows_root = any(k == "disallow" and v in ("/", "/*") for k, v in rules)
    allows_root = any(k == "allow" and v in ("/", "/*") for k, v in rules)
    return disallows_root and not allows_root


def blocks_all(body: str) -> bool:
    """``Disallow: /`` para todos (``*``) o para Googlebot: la web entera fuera de Google."""
    groups, _ = parse_robots(body)
    return any(_group_blocks_all(groups[agent]) for agent in ("*", "googlebot") if agent in groups)


def robots_hash(body: str) -> str:
    """Hash del contenido normalizado (saltos de línea y espacios al final no cuentan)."""
    normalized = "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return hashlib.sha256(normalized.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RobotsRead:
    status: str                 # ok | missing | error
    body: str | None = None     # "" si no existe (para Google es "todo permitido")
    error: str | None = None
    sitemaps: tuple[str, ...] = ()


def read_robots(result: FetchResult) -> RobotsRead:
    if result.error is not None or result.status_code is None:
        return RobotsRead("error", error=cause_label(result.error) or "sin respuesta")
    code = result.status_code
    if code in (404, 410):
        return RobotsRead("missing", body="")
    if not 200 <= code < 300:
        return RobotsRead("error", error=f"error HTTP {code}")
    body = decode_body(result).lstrip("﻿")
    _, sitemaps = parse_robots(body)
    return RobotsRead("ok", body=body, sitemaps=tuple(sitemaps))


def origin_of(url: str) -> str | None:
    """``https://host`` (sin puerto por defecto) de una URL válida; None si no lo es."""
    try:
        host = check_url_syntax(url)
    except SSRFError:
        return None
    scheme = urlparse(url.strip()).scheme.lower()
    return f"{scheme}://{host}"


# ── RDAP ─────────────────────────────────────────────────────────────


def parse_bootstrap(data: dict) -> dict[str, str]:
    """TLD -> URL base del servidor RDAP (la primera https)."""
    out: dict[str, str] = {}
    for service in data.get("services", []):
        if not isinstance(service, list) or len(service) < 2:
            continue
        tlds, urls = service[0], service[1]
        base = next((u for u in urls if isinstance(u, str) and u.startswith("https://")), None)
        if not base:
            continue
        for tld in tlds:
            if isinstance(tld, str):
                out[tld.lower()] = base if base.endswith("/") else base + "/"
    return out


def domain_candidates(host: str) -> list[str]:
    """Del nombre más largo al registrable más corto posible (dos etiquetas), sin ``www.``."""
    labels = host.lower().rstrip(".").removeprefix("www.").split(".")
    out = [".".join(labels[i:]) for i in range(len(labels) - 1)]
    return out[-_RDAP_MAX_CANDIDATES:]


def rdap_expiration(data: dict) -> datetime | None:
    for event in data.get("events", []) or []:
        if isinstance(event, dict) and str(event.get("eventAction", "")).lower() == "expiration":
            raw = event.get("eventDate")
            if isinstance(raw, str):
                try:
                    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    return None
                return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


@dataclass(frozen=True)
class DomainInfo:
    status: str                 # ok | no_date | unsupported | not_found | error
    name: str | None = None
    expires_at: datetime | None = None
    error: str | None = None


async def lookup_domain(host: str, bootstrap: dict[str, str] | None, *, fetcher=None) -> DomainInfo:
    fetcher = fetcher or fetch
    if bootstrap is None:
        return DomainInfo("error", error="no se pudo consultar el registro de la IANA")
    try:
        ipaddress.ip_address(host)
        return DomainInfo("not_found")  # una IP no tiene dominio que caduque
    except ValueError:
        pass
    candidates = domain_candidates(host)
    if not candidates:
        return DomainInfo("not_found")
    tld = candidates[-1].rsplit(".", 1)[-1]
    base = bootstrap.get(tld)
    if base is None:
        return DomainInfo("unsupported")
    for name in candidates:
        result = await fetcher(f"{base}domain/{name}", timeout=_RDAP_TIMEOUT_S,
                               max_bytes=_RDAP_MAX_BYTES, accept=RDAP_ACCEPT)
        if result.error is not None or result.status_code is None:
            return DomainInfo("error", error=cause_label(result.error) or "sin respuesta")
        if result.status_code == 404:
            continue
        if not 200 <= result.status_code < 300:
            return DomainInfo("error", error=f"el registro respondió error HTTP {result.status_code}")
        try:
            data = await asyncio.to_thread(json.loads, result.body)
        except ValueError:
            return DomainInfo("error", error="respuesta RDAP no válida")
        expires = rdap_expiration(data) if isinstance(data, dict) else None
        return DomainInfo("ok" if expires else "no_date", name=name, expires_at=expires)
    return DomainInfo("not_found")


async def load_bootstrap(*, fetcher=None) -> dict[str, str] | None:
    fetcher = fetcher or fetch
    result = await fetcher(RDAP_BOOTSTRAP_URL, timeout=_RDAP_TIMEOUT_S, max_bytes=_BOOTSTRAP_MAX_BYTES,
                           accept="application/json")
    if result.error is not None or result.status_code != 200:
        logger.warning("Web health: el registro RDAP de la IANA no responde (%s)", result.error or result.status_code)
        return None
    try:
        return parse_bootstrap(await asyncio.to_thread(json.loads, result.body))
    except (ValueError, AttributeError):
        logger.warning("Web health: el registro RDAP de la IANA no es JSON válido")
        return None


# ── Pasada ───────────────────────────────────────────────────────────


@dataclass
class HealthResult:
    hosts: int = 0
    origins: int = 0
    bootstrap_failed: bool = False


async def _gather_limited(coros, limit: int = MAX_CONCURRENCY):
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


async def expiry_targets(db) -> dict[int, dict[str, bool]]:
    """{cliente: {host: hay alguna URL https}} de las URLs de disponibilidad vigiladas."""
    rows = (await db.execute(
        select(WebUptimeTarget.client_id, WebUptimeTarget.url)
        .join(Client, Client.id == WebUptimeTarget.client_id)
        .where(monitored_clause())
        .order_by(WebUptimeTarget.client_id, WebUptimeTarget.id)
    )).all()
    out: dict[int, dict[str, bool]] = {}
    for row in rows:
        try:
            host = check_url_syntax(row.url)
        except SSRFError:
            continue
        https = urlparse(row.url.strip()).scheme.lower() == "https"
        hosts = out.setdefault(row.client_id, {})
        hosts[host] = hosts.get(host, False) or https
    return out


async def check_expiry(session_factory, now: datetime, *, fetcher=None, cert_reader=None) -> HealthResult:
    result = HealthResult()
    cert_reader = cert_reader or fetch_tls_certificate
    async with session_factory() as db:
        per_client = await expiry_targets(db)
    hosts: dict[str, bool] = {}
    for client_hosts in per_client.values():
        for host, https in client_hosts.items():
            hosts[host] = hosts.get(host, False) or https
    result.hosts = len(hosts)

    certs: dict[str, TlsCertificate | None] = {}
    domains: dict[str, DomainInfo] = {}
    if hosts:
        bootstrap = await load_bootstrap(fetcher=fetcher)
        result.bootstrap_failed = bootstrap is None
        names = sorted(hosts)
        cert_list = await _gather_limited([
            cert_reader(host, timeout=_TLS_TIMEOUT_S) if hosts[host] else _none() for host in names
        ])
        certs = dict(zip(names, cert_list))
        # Un mismo dominio puede venir de www y sin www: una consulta por nombre.
        bare = sorted({host.removeprefix("www.") for host in names})
        domain_list = await _gather_limited([lookup_domain(name, bootstrap, fetcher=fetcher) for name in bare])
        by_bare = dict(zip(bare, domain_list))
        domains = {host: by_bare[host.removeprefix("www.")] for host in names}

    async with session_factory() as db:
        existing = {(r.client_id, r.host): r for r in (await db.scalars(select(WebHostExpiry))).all()}
        keep = set()
        for client_id, client_hosts in per_client.items():
            for host in client_hosts:
                keep.add((client_id, host))
                row = existing.get((client_id, host))
                if row is None:
                    row = WebHostExpiry(client_id=client_id, host=host)
                    db.add(row)
                _apply_expiry(row, certs.get(host), domains[host], now)
        for key, row in existing.items():
            if key not in keep:
                await db.delete(row)
        await db.commit()
    return result


async def _none():
    return None


def _apply_expiry(row: WebHostExpiry, cert: TlsCertificate | None, domain: DomainInfo, now: datetime) -> None:
    row.checked_at = now
    if cert is None:
        row.cert_status, row.cert_expires_at, row.cert_issuer, row.cert_error = "no_https", None, None, None
    elif cert.error is not None:
        # Sin certificado que leer hoy: se conserva la última fecha conocida.
        row.cert_status, row.cert_error = "error", cause_label(cert.error)
    else:
        row.cert_status = "ok" if cert.verified else "invalid"
        row.cert_expires_at, row.cert_issuer = cert.not_after, cert.issuer
        row.cert_error = None if cert.verified else (cert.verify_error or "certificado no válido")[:200]
    row.domain_status, row.domain_error = domain.status, domain.error
    if domain.status == "error":
        return  # se conserva la última fecha conocida
    row.domain_name = domain.name
    row.domain_expires_at = domain.expires_at


async def robots_targets(db) -> dict[int, tuple[list[str], str | None]]:
    """{cliente: (orígenes, user-agent)} de clientes con la vigilancia de cambios encendida."""
    clients = (await db.execute(
        select(Client.id, Client.website, ClientWebSettings.user_agent)
        .join(ClientWebSettings, ClientWebSettings.client_id == Client.id)
        .where(monitored_clients_clause(), ClientWebSettings.changes_enabled.is_(True))
        .order_by(Client.id)
    )).all()
    if not clients:
        return {}
    watched = (await db.execute(
        select(WebWatch.client_id, WebWatch.url)
        .where(WebWatch.client_id.in_([c.id for c in clients]), watched_clause())
        .order_by(WebWatch.client_id, WebWatch.url)
    )).all()
    by_client: dict[int, list[str]] = {}
    for row in watched:
        origin = origin_of(row.url)
        if origin and origin not in by_client.setdefault(row.client_id, []):
            by_client[row.client_id].append(origin)
    out = {}
    for client in clients:
        origins = by_client.get(client.id) or []
        if not origins and client.website:
            website = client.website if "://" in client.website else f"https://{client.website}"
            origin = origin_of(website)
            origins = [origin] if origin else []
        if origins:
            out[client.id] = (origins[:MAX_ORIGINS_PER_CLIENT], client.user_agent)
    return out


@dataclass(frozen=True)
class SitemapRead:
    url: str
    source: str                  # declared | default
    status: str                  # ok | empty | invalid | error
    count: int | None = None
    has_more: bool | None = None
    error: str | None = None


async def read_sitemap(origin: str, robots: RobotsRead, user_agent: str | None, *, fetcher=None) -> SitemapRead:
    fetcher = fetcher or fetch
    declared = [s for s in robots.sitemaps if s.startswith(("http://", "https://"))]
    url, source = (declared[0], "declared") if declared else (f"{origin}/sitemap.xml", "default")
    url = url[:500]
    try:
        urls, has_more = await asyncio.wait_for(
            fetch_sitemap_urls(url, limit=SITEMAP_URL_LIMIT, user_agent=user_agent, fetcher=fetcher),
            _SITEMAP_TIMEOUT_S,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return SitemapRead(url, source, "error", error="no responde a tiempo")
    except ValueError as exc:
        # fetch_sitemap_urls levanta ValueError con el motivo si el sitemap principal no responde.
        return SitemapRead(url, source, "error", error=str(exc)[:200] or "sin respuesta")
    except Exception:  # noqa: BLE001 — XML roto (lxml) o gzip inválido
        return SitemapRead(url, source, "invalid", error="no es un XML de sitemap válido")
    if not urls:
        return SitemapRead(url, source, "empty", count=0, has_more=False)
    return SitemapRead(url, source, "ok", count=len(urls), has_more=has_more)


async def _check_origin(origin: str, user_agent: str | None, fetcher) -> tuple[RobotsRead, SitemapRead]:
    fetched = await fetcher(f"{origin}/robots.txt", user_agent=user_agent, timeout=_ROBOTS_TIMEOUT_S,
                            max_bytes=ROBOTS_MAX_BYTES)
    robots = read_robots(fetched)
    sitemap = await read_sitemap(origin, robots, user_agent, fetcher=fetcher)
    return robots, sitemap


def apply_robots(row: WebRobotsState, robots: RobotsRead, sitemap: SitemapRead, now: datetime) -> bool:
    """Actualiza la fila. Devuelve True si el robots.txt cambió respecto al último leído."""
    row.checked_at = now
    row.robots_status = robots.status
    row.robots_error = robots.error
    changed = False
    if robots.status != "error":
        body = robots.body or ""
        digest = robots_hash(body)
        if row.robots_hash is not None and row.robots_hash != digest:
            changed = True
            row.robots_previous_body = row.robots_body
            row.robots_changed_at = now
            row.robots_reviewed_at = None
            row.robots_reviewed_by = None
        row.robots_hash = digest
        row.robots_body = body[:ROBOTS_STORED_CHARS]
        row.robots_blocks_all = blocks_all(body)
    row.sitemap_url, row.sitemap_source, row.sitemap_status = sitemap.url, sitemap.source, sitemap.status
    row.sitemap_url_count, row.sitemap_has_more, row.sitemap_error = sitemap.count, sitemap.has_more, sitemap.error
    return changed


async def check_robots(session_factory, now: datetime, *, fetcher=None) -> HealthResult:
    result = HealthResult()
    fetcher = fetcher or fetch
    async with session_factory() as db:
        per_client = await robots_targets(db)
    jobs = [(client_id, origin, ua) for client_id, (origins, ua) in per_client.items() for origin in origins]
    result.origins = len(jobs)
    reads = await _gather_limited([_check_origin(origin, ua, fetcher) for _, origin, ua in jobs])

    async with session_factory() as db:
        existing = {(r.client_id, r.origin): r for r in (await db.scalars(select(WebRobotsState))).all()}
        keep = set()
        for (client_id, origin, _ua), (robots, sitemap) in zip(jobs, reads):
            keep.add((client_id, origin))
            row = existing.get((client_id, origin))
            if row is None:
                row = WebRobotsState(client_id=client_id, origin=origin, robots_blocks_all=False)
                db.add(row)
            apply_robots(row, robots, sitemap, now)
        for key, row in existing.items():
            if key not in keep:
                await db.delete(row)
        await db.commit()
    return result


async def run_cycle(session_factory, *, now: datetime | None = None, fetcher=None, cert_reader=None,
                    expiry: bool | None = None, robots: bool | None = None) -> HealthResult:
    """Una pasada diaria. Cada parte sólo corre con el interruptor de su módulo de Webs."""
    now = now or datetime.now(UTC)
    expiry = settings.UPTIME_ENABLED if expiry is None else expiry
    robots = settings.WEB_SWEEP_ENABLED if robots is None else robots
    result = HealthResult()
    if expiry:
        part = await check_expiry(session_factory, now, fetcher=fetcher, cert_reader=cert_reader)
        result.hosts, result.bootstrap_failed = part.hosts, part.bootstrap_failed
    if robots:
        part = await check_robots(session_factory, now, fetcher=fetcher)
        result.origins = part.origins
    logger.info("Web health: %d hosts (caducidad), %d orígenes (robots/sitemap)", result.hosts, result.origins)
    return result

