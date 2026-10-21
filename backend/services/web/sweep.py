"""El barrido: comprobar las URLs vigiladas de un cliente y avisar de lo que cambió.

Reescrito desde ``Vigil/backend/app/services/sweep.py`` (SQLite síncrono) a
SQLAlchemy async. Flujo por URL:

    fetch → extraer → comparar hashes → si algo cambió: captura + clasificar
    → guardar el cambio → siempre: actualizar ``web_watch_state``

Reglas que se conservan de Vigil:

  * Una URL que falla NO tumba el barrido: se anota en ``web_run_errors`` y sigue.
  * Un cliente que falla NO tumba a los demás (``run_cycle``).
  * Un fallo de Slack NO invalida el barrido: los cambios ya están guardados y
    el motivo queda en ``web_sweep_runs.notify_status``/``notify_error``.
  * Los cuerpos sólo se guardan cuando algún hash cambió: si nada cambió, la
    última captura guardada ES la de hoy.
  * Circuit breaker por host: si más del 30 % de las URLs de un host fallan (con
    al menos 4), ese host no se clasifica: un WAF que devuelve 403 a todo no son
    40 páginas caídas. NUEVO: un 401/403/429 o un desafío cuenta como fallo
    (``unreachable``; en Vigil sólo contaba la falta de respuesta), y se cruza con
    el monitor de disponibilidad
    (``web_uptime_state``): si dice que la web está caída, el aviso lo dice; si
    no, "probable bloqueo".
  * Lo marcado "en curso" (``checking_since``, barridos ``running``) se recoge al
    empezar cada ciclo del job (``reap_orphans``).

Regla nueva de The Agency: el trabajo de CPU (lxml, hashes, difflib, gzip) va en
``asyncio.to_thread``. Este proceso es también el servidor web: una página de
Elementor de 300 KB tarda decenas de milisegundos en parsearse y un diff
cuadrático puede tardar segundos; en el bucle de eventos congelaría la API.
Las llamadas a red y a Slack se hacen SIN transacción abierta.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import random
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dtime, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from sqlalchemy import and_, delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from backend.config import settings
from backend.core.security import decrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, WebChange, WebChangeItem, WebRunError, WebSnapshot, WebSweepRun,
    WebUptimeState, WebUptimeTarget, WebWatch, WebWatchState,
)
from backend.services.temporal import business_zone
from backend.services.web import capture_defaults as defaults
from backend.services.web.calendario import toca_barrido
from backend.services.web.classifier import _ORDER, ChangeItem, classify, max_severity
from backend.services.web.digest import DigestChange, build_digest, build_summary, changes_url
from backend.services.web.extractor import Capture, CaptureConfig, extract
from backend.services.web.html_diff import delta_stats
from backend.services.web.safe_http import FetchResult, fetch
from backend.services.web.slack import post_message
from backend.services.web.uptime import cause_label
from backend.services.web.uptime import classify as uptime_classify

logger = logging.getLogger(__name__)

# Si más del 30 % de las URLs de un host fallan, se corta ese host.
CIRCUIT_THRESHOLD = 0.30
CIRCUIT_MIN_URLS = 4
# Texto inline hasta 32 KB; por encima sólo va comprimido.
MAX_INLINE_TEXT = 32 * 1024
# Una página de cliente, como mucho. Lo que pase de aquí se recorta.
MAX_BODY_BYTES = 5 * 1024 * 1024
# Lo que puede durar la parte de red de un barrido. El job tiene 900 s; lo que
# no se haya descargado en este tiempo queda como error ``budget`` del barrido.
FETCH_BUDGET_SECONDS = 600.0
# Un ciclo no empieza otro cliente "a mano" pasado este tiempo, ni el programado
# pasado ``SCHEDULED_START_LIMIT``: lo que quede, en el ciclo siguiente (60 s).
MANUAL_BUDGET_SECONDS = 480.0
SCHEDULED_START_LIMIT = 120.0
# Marcas de "comprobando" más viejas que esto no se enseñan (``progress``).
STALE_MARK_MINUTES = 45

Fetcher = Callable[..., Awaitable[FetchResult]]
Poster = Callable[..., Awaitable[Any]]
Sleeper = Callable[[float], Awaitable[None]]

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


# ---------------------------------------------------------------------------
# Config efectiva
# ---------------------------------------------------------------------------


def _str_list(raw) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(x for x in raw if isinstance(x, str))


@dataclass(frozen=True)
class SweepSettings:
    """Ajustes de un cliente ya resueltos: lo guardado o, si es NULL, el código."""

    content_selector: str | None = None
    ignore_selectors: tuple[str, ...] = defaults.DEFAULT_IGNORE_SELECTORS
    ignore_regexes: tuple[str, ...] = defaults.DEFAULT_IGNORE_REGEXES
    max_concurrency: int = defaults.DEFAULT_MAX_CONCURRENCY
    request_timeout_s: int = defaults.DEFAULT_REQUEST_TIMEOUT_S
    crawl_delay_ms: int = defaults.DEFAULT_CRAWL_DELAY_MS
    user_agent: str | None = None
    digest_min_severity: str = defaults.DEFAULT_DIGEST_MIN_SEVERITY
    sweep_weekdays: tuple[int, ...] = defaults.DEFAULT_SWEEP_WEEKDAYS
    sweep_skip_dates: tuple[str, ...] = ()
    sweep_summary_to_slack: bool = defaults.DEFAULT_SWEEP_SUMMARY_TO_SLACK

    def calendar(self) -> dict:
        return {"sweep_weekdays": list(self.sweep_weekdays), "sweep_skip_dates": list(self.sweep_skip_dates)}


def effective_settings(web: ClientWebSettings | None) -> SweepSettings:
    """NULL (o no hay fila) = el default de ``capture_defaults``. Una lista
    guardada, aunque esté vacía, manda: un cliente puede querer no podar nada."""
    if web is None:
        return SweepSettings()
    weekdays = tuple(d for d in (web.sweep_weekdays or []) if isinstance(d, int) and 1 <= d <= 7)
    return SweepSettings(
        content_selector=web.default_content_selector or None,
        ignore_selectors=(_str_list(web.default_ignore_selectors) if web.default_ignore_selectors is not None
                          else defaults.DEFAULT_IGNORE_SELECTORS),
        ignore_regexes=(_str_list(web.default_ignore_regexes) if web.default_ignore_regexes is not None
                        else defaults.DEFAULT_IGNORE_REGEXES),
        max_concurrency=web.max_concurrency or defaults.DEFAULT_MAX_CONCURRENCY,
        request_timeout_s=web.request_timeout_s or defaults.DEFAULT_REQUEST_TIMEOUT_S,
        crawl_delay_ms=(web.crawl_delay_ms if web.crawl_delay_ms is not None else defaults.DEFAULT_CRAWL_DELAY_MS),
        user_agent=web.user_agent,
        digest_min_severity=web.digest_min_severity or defaults.DEFAULT_DIGEST_MIN_SEVERITY,
        sweep_weekdays=(weekdays if web.sweep_weekdays is not None and weekdays
                        else defaults.DEFAULT_SWEEP_WEEKDAYS),
        sweep_skip_dates=_str_list(web.sweep_skip_dates),
        sweep_summary_to_slack=(web.sweep_summary_to_slack if web.sweep_summary_to_slack is not None
                                else defaults.DEFAULT_SWEEP_SUMMARY_TO_SLACK),
    )


def effective_config(watch, cfg: SweepSettings) -> CaptureConfig:
    """Resuelve URL → cliente. La URL pisa; NULL (o lista vacía, como en Vigil) hereda."""
    return CaptureConfig(
        content_selector=watch.content_selector or cfg.content_selector,
        ignore_selectors=_str_list(watch.ignore_selectors) or cfg.ignore_selectors,
        ignore_regexes=_str_list(watch.ignore_regexes) or cfg.ignore_regexes,
    )


def slack_state(web: ClientWebSettings | None) -> str:
    """``ready`` | ``disabled`` | ``revoked``. Se lee de la CONFIGURACIÓN, nunca
    del último barrido (lección 0sexies de Vigil)."""
    if web is None or not web.slack_webhook_url:
        return "disabled"
    if web.slack_revoked_at is not None:
        return "revoked"
    return "ready" if web.slack_enabled else "disabled"


def monitored_clients_clause():
    return and_(Client.status == ClientStatus.active, Client.is_internal.is_(False))


def watched_clause():
    """URLs que entran en un barrido: activas y no archivadas."""
    return and_(WebWatch.is_active.is_(True), WebWatch.archived_at.is_(None))


def local_date(instant: datetime) -> date:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(business_zone()).date()


def date_label(day: date) -> str:
    return f"{day.day} {_MESES[day.month - 1]} {day.year}"


# ---------------------------------------------------------------------------
# Red
# ---------------------------------------------------------------------------


def fetch_ok(result: FetchResult | None) -> bool:
    """Hubo respuesta HTTP. Un 404 es una respuesta (y un cambio: STATUS_ERROR)."""
    return result is not None and result.error is None and result.status_code is not None


_CHARSET = re.compile(r"charset=[\"']?([\w.:-]+)", re.I)


def decode_body(result: FetchResult) -> str:
    """Igual que ``httpx.Response.text``: charset de la cabecera o UTF-8."""
    match = _CHARSET.search(result.headers.get("content-type", ""))
    encoding = match.group(1) if match else "utf-8"
    try:
        return result.body.decode(encoding, errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


async def fetch_many(
    items: list[tuple[Any, str]], *, max_concurrency: int, timeout_s: float, delay_ms: int,
    user_agent: str | None, fetcher: Fetcher = fetch, sleep: Sleeper = asyncio.sleep,
    budget: float = FETCH_BUDGET_SECONDS,
) -> dict[Any, FetchResult]:
    """Pide todas las URLs. Nunca lanza: los fallos vienen en cada FetchResult.

    Cortesía (Vigil): cada host en serie con su retardo y jitter; hosts distintos
    en paralelo, como mucho ``max_concurrency`` peticiones a la vez. Lo que no
    termine dentro de ``budget`` se queda sin resultado.
    """
    by_host: dict[str, list[tuple[Any, str]]] = {}
    for key, url in items:
        by_host.setdefault(host_of(url), []).append((key, url))
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    results: dict[Any, FetchResult] = {}

    async def walk(queue: list[tuple[Any, str]]) -> None:
        for index, (key, url) in enumerate(queue):
            if index and delay_ms:
                # Jitter: un intervalo exacto es una huella de bot para muchos WAF.
                await sleep(delay_ms * random.uniform(0.75, 1.25) / 1000)  # noqa: S311
            async with semaphore:
                results[key] = await fetcher(url, user_agent=user_agent, timeout=float(timeout_s),
                                             max_bytes=MAX_BODY_BYTES)

    tasks = [asyncio.create_task(walk(queue)) for queue in by_host.values()]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=budget)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    return results


# ---------------------------------------------------------------------------
# Una URL: CPU (en hilo) y base de datos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WatchRow:
    """Copia plana de ``WebWatch``: viaja entre sesiones y al hilo."""

    id: uuid.UUID
    client_id: int
    url: str
    label: str | None
    muted: bool
    watch_seo: bool
    watch_content: bool
    watch_links: bool
    watch_html: bool
    content_selector: str | None
    ignore_selectors: Any
    ignore_regexes: Any

    @classmethod
    def of(cls, w: WebWatch) -> "WatchRow":
        return cls(w.id, w.client_id, w.url, w.label, bool(w.muted), bool(w.watch_seo), bool(w.watch_content),
                   bool(w.watch_links), bool(w.watch_html), w.content_selector, w.ignore_selectors,
                   w.ignore_regexes)

    def flags(self) -> dict[str, bool]:
        return {"watch_seo": self.watch_seo, "watch_content": self.watch_content,
                "watch_links": self.watch_links, "watch_html": self.watch_html}


@dataclass
class WatchOutcome:
    watch_id: uuid.UUID
    ok: bool
    changed: bool = False
    items: list[ChangeItem] = field(default_factory=list)
    change_id: uuid.UUID | None = None
    error: str | None = None
    error_kind: str | None = None


@dataclass(frozen=True)
class Comparison:
    items: list[ChangeItem]
    something_changed: bool
    text_inline: str | None = None
    text_gz: bytes | None = None
    html_gz: bytes | None = None


def _gunzip(data: bytes | None) -> str | None:
    return gzip.decompress(data).decode() if data else None


def compare(
    *, capture: Capture, flags: dict[str, bool], prev_hashes: dict[str, str | None] | None,
    prev_seo: dict | None, prev_links: dict | None, prev_text_inline: str | None,
    prev_text_gz: bytes | None, prev_html_gz: bytes | None, store_html: bool,
) -> Comparison:
    """Clasifica contra lo anterior y prepara los cuerpos a guardar. CPU pura:
    se llama con ``asyncio.to_thread``."""
    prev_hashes = prev_hashes or {}
    html_changed = prev_hashes.get("html") != capture.hashes["html"]
    prev_text = None
    if prev_seo is not None and flags["watch_content"]:
        prev_text = prev_text_inline or _gunzip(prev_text_gz)
    prev_html = _gunzip(prev_html_gz) if (prev_seo is not None and flags["watch_html"] and html_changed) else None
    # Sólo se mide si hace falta: el clasificador sólo usa el delta cuando el
    # HTML es lo ÚNICO que se movió, y ``delta_stats`` recorre las dos páginas.
    html_delta = delta_stats(prev_html, capture.html) if prev_html else None
    items = classify(
        prev_seo=prev_seo, curr_seo=capture.seo,
        prev_text=prev_text, curr_text=capture.text,
        prev_links=prev_links, curr_links=capture.links,
        html_changed=html_changed, html_delta=html_delta, watch_flags=flags,
    )
    something_changed = any(prev_hashes.get(dim) != capture.hashes[dim] for dim in ("seo", "content", "links", "html"))
    if not (something_changed or prev_seo is None):
        return Comparison(items, something_changed)
    text = capture.text or ""
    inline = text if len(text.encode()) <= MAX_INLINE_TEXT else None
    return Comparison(
        items, something_changed,
        text_inline=inline,
        text_gz=gzip.compress(text.encode()) if inline is None else None,
        html_gz=gzip.compress((capture.html or "").encode()) if store_html else None,
    )


def _error_message(result: FetchResult | None) -> tuple[str, str]:
    if result is None:
        return "budget", "No dio tiempo a mirarla en este barrido"
    if result.error:
        return result.error, cause_label(result.error) or result.error
    return "error", "Sin respuesta"


async def _record_fetch_error(session_factory, watch: WatchRow, message: str, now: datetime) -> None:
    async with session_factory() as db:
        stmt = pg_insert(WebWatchState).values(
            watch_id=watch.id, client_id=watch.client_id, last_checked_at=now, last_error=message[:500],
            consecutive_errors=1, updated_at=now,
        )
        await db.execute(stmt.on_conflict_do_update(
            index_elements=[WebWatchState.watch_id],
            set_={"last_checked_at": now, "last_error": message[:500], "updated_at": now,
                  "consecutive_errors": WebWatchState.consecutive_errors + 1},
        ))
        await db.commit()


async def process_watch(
    session_factory, *, watch: WatchRow, cfg: SweepSettings, result: FetchResult, run_id: uuid.UUID,
    now: datetime,
) -> WatchOutcome:
    """Procesa la respuesta de una URL. Lanza sólo si falla la base de datos."""
    if not fetch_ok(result):
        kind, message = _error_message(result)
        await _record_fetch_error(session_factory, watch, message, now)
        return WatchOutcome(watch.id, ok=False, error=message, error_kind=kind)

    capture_cfg = effective_config(watch, cfg)
    try:
        capture = await asyncio.to_thread(
            extract, decode_body(result), base_url=watch.url, final_url=result.final_url or watch.url,
            status_code=result.status_code or 0, headers=result.headers, cfg=capture_cfg,
        )
    except Exception as exc:  # noqa: BLE001 — una página rota no tumba el barrido
        logger.warning("Webs: no se pudo analizar %s (%s)", watch.url, type(exc).__name__)
        return WatchOutcome(watch.id, ok=False, error=f"No se pudo analizar la página: {type(exc).__name__}",
                            error_kind="parse")

    async with session_factory() as db:
        state = await db.get(WebWatchState, watch.id, populate_existing=True)
        prev_seo = state.seo_json if state is not None else None
        prev_links = state.links_json if state is not None else None
        prev_hashes = ({"seo": state.hash_seo, "content": state.hash_content, "links": state.hash_links,
                        "html": state.hash_html} if state is not None else None)
        prev_snapshot_id = state.last_snapshot_id if state is not None else None
        # El cuerpo anterior sale de la última captura, en UNA consulta: el texto
        # para clasificar contenido y el HTML para medir el cambio de maquetación.
        prev_bodies: dict[str, Any] = {}
        if prev_seo is not None and prev_snapshot_id and (watch.watch_content or watch.watch_html):
            columns = [WebSnapshot.text_inline, WebSnapshot.text_gz]
            if watch.watch_html:
                columns.append(WebSnapshot.html_gz)
            row = (await db.execute(select(*columns).where(WebSnapshot.id == prev_snapshot_id))).one_or_none()
            prev_bodies = dict(row._mapping) if row is not None else {}
        await db.commit()  # sólo lectura: nada abierto mientras se compara

    comparison = await asyncio.to_thread(
        compare, capture=capture, flags=watch.flags(), prev_hashes=prev_hashes, prev_seo=prev_seo,
        prev_links=prev_links, prev_text_inline=prev_bodies.get("text_inline"),
        prev_text_gz=prev_bodies.get("text_gz"), prev_html_gz=prev_bodies.get("html_gz"),
        store_html=watch.watch_html,
    )

    async with session_factory() as db:
        snapshot_id = None
        if comparison.something_changed or prev_seo is None:
            snapshot_id = uuid.uuid4()
            db.add(WebSnapshot(
                id=snapshot_id, watch_id=watch.id, client_id=watch.client_id, run_id=run_id, captured_at=now,
                content_hash=capture.hashes["content"], html_hash=capture.hashes["html"],
                status_code=result.status_code, byte_size=len(result.body),
                text_gz=comparison.text_gz, html_gz=comparison.html_gz, text_inline=comparison.text_inline,
            ))
            await db.flush()
        change_id = None
        if comparison.items:
            change_id = uuid.uuid4()
            db.add(WebChange(
                id=change_id, client_id=watch.client_id, watch_id=watch.id, run_id=run_id,
                snapshot_id=snapshot_id, prev_snapshot_id=prev_snapshot_id,
                max_severity=max_severity(comparison.items), detected_at=now,
            ))
            await db.flush()
            db.add_all([WebChangeItem(
                change_id=change_id, client_id=watch.client_id, kind=i.kind, field=i.field,
                severity=i.severity, rule_code=i.rule_code, before_val=i.before_val, after_val=i.after_val,
                detail=i.detail or None, created_at=now,
            ) for i in comparison.items])
        values = {
            "last_checked_at": now, "last_status_code": result.status_code, "last_final_url": result.final_url,
            "last_error": None, "consecutive_errors": 0,
            "hash_seo": capture.hashes["seo"], "hash_content": capture.hashes["content"],
            "hash_links": capture.hashes["links"], "hash_html": capture.hashes["html"],
            "seo_json": capture.seo, "links_json": capture.links,
            "needs_js_render": capture.needs_js_render, "scope_missed": capture.scope_missed, "updated_at": now,
        }
        if comparison.items:
            values["last_changed_at"] = now
        if snapshot_id is not None:
            values["last_snapshot_id"] = snapshot_id
        stmt = pg_insert(WebWatchState).values(watch_id=watch.id, client_id=watch.client_id, **values)
        await db.execute(stmt.on_conflict_do_update(index_elements=[WebWatchState.watch_id], set_=values))
        await db.commit()

    return WatchOutcome(watch.id, ok=True, changed=bool(comparison.items), items=comparison.items,
                        change_id=change_id)


# ---------------------------------------------------------------------------
# Un cliente
# ---------------------------------------------------------------------------


def unreachable(result: FetchResult | None) -> bool:
    """Para el circuit breaker, "fallo" es no poder mirar la página: sin
    respuesta HTTP o un bloqueo (401/403/429 o desafío de Cloudflare, la misma
    regla que el monitor de caídas). En Vigil sólo contaba lo primero, así que un
    WAF que respondía 403 a todo producía un "la página devuelve error" crítico
    por URL: justo el falso positivo masivo que el circuito existe para evitar."""
    if not fetch_ok(result):
        return True
    return uptime_classify(result).outcome == "blocked"


def circuit_open_hosts(results: dict, watches: list[WatchRow]) -> dict[str, tuple[int, int]]:
    """Hosts con demasiados fallos: probablemente un WAF, no 40 páginas rotas.
    Devuelve {host: (fallidas, miradas)}."""
    by_host: dict[str, list[bool]] = defaultdict(list)
    for watch in watches:
        if watch.id in results:
            by_host[host_of(watch.url)].append(not unreachable(results[watch.id]))
    out = {}
    for host, oks in by_host.items():
        failed = oks.count(False)
        if len(oks) >= CIRCUIT_MIN_URLS and failed / len(oks) > CIRCUIT_THRESHOLD:
            out[host] = (failed, len(oks))
    return out


def _bare(host: str) -> str:
    return host.removeprefix("www.")


async def uptime_by_host(db, client_id: int) -> dict[str, str]:
    """Lo que dice el monitor de disponibilidad de cada host del cliente
    (``down`` gana a ``blocked`` y éste al resto)."""
    rows = (await db.execute(
        select(WebUptimeTarget.url, WebUptimeState.status)
        .join(WebUptimeState, WebUptimeState.target_id == WebUptimeTarget.id)
        .where(WebUptimeTarget.client_id == client_id, WebUptimeTarget.is_active.is_(True))
    )).all()
    rank = {"down": 0, "blocked": 1}
    out: dict[str, str] = {}
    for url, status in rows:
        host = _bare(host_of(url))
        if host not in out or rank.get(status, 9) < rank.get(out[host], 9):
            out[host] = status
    return out


def circuit_note(host: str, failed: int, total: int, uptime_status: str | None) -> str:
    base = f"{host}: no se han podido mirar {failed} de {total} páginas"
    if uptime_status == "down":
        return f"{base}. La web está caída según el monitor de disponibilidad. No se han generado avisos de cambios."
    if uptime_status == "blocked":
        return f"{base}. El monitor de disponibilidad también ve un bloqueo (WAF/anti-bots), no páginas caídas."
    return f"{base}. Probable bloqueo (WAF/anti-bots), no páginas caídas. No se han generado avisos de cambios."


async def reap_orphans(session_factory, *, now: datetime | None = None) -> tuple[int, int]:
    """Cierra los barridos ``running`` y limpia las marcas ``checking_since``.

    Sin margen de tiempo, a diferencia del recolector de 45 min de Vigil: esto
    corre DENTRO del job ``web_sweep``, que tiene el lock 16; mientras lo
    tenemos, ningún otro barrido puede estar vivo, así que lo que figure "en
    curso" es rastro de un deploy o de un ciclo cortado por el timeout. Sin esto
    la interfaz se quedaría girando (lección 0ter de Vigil).
    """
    now = now or datetime.now(UTC)
    async with session_factory() as db:
        runs = (await db.execute(
            update(WebSweepRun).where(WebSweepRun.status == "running")
            .values(status="partial", finished_at=now)
        )).rowcount or 0
        marks = (await db.execute(
            update(WebWatchState).where(WebWatchState.checking_since.is_not(None)).values(checking_since=None)
        )).rowcount or 0
        await db.commit()
    if runs or marks:
        logger.warning("Webs: %d barridos huérfanos cerrados y %d marcas de comprobación limpiadas", runs, marks)
    return runs, marks


async def _notify(
    session_factory, *, client_id: int, client_name: str, web_state: str, webhook_enc: str | None,
    cfg: SweepSettings, cambios: list[DigestChange], urls_checked: int, n_err: int, notes: list[str],
    trigger: str, completo: bool, day: date, post: Poster,
) -> tuple[str, str | None, bool]:
    """Avisa a Slack del cliente. Devuelve (notify_status, notify_error, enviado).

    Los motivos de NO avisar se distinguen (lección 0sexies de Vigil):
    ``no_procede`` (no tocaba avisar), ``disabled`` (sin Slack) y ``revoked``.
    """
    if web_state != "ready":
        return web_state, None, False
    try:
        webhook = decrypt_vault_secret(webhook_enc)
    except ValueError:
        return "failed", "No se pudo descifrar el webhook (¿cambió VAULT_KEY?)", False

    minimum = _ORDER.get(cfg.digest_min_severity, _ORDER["info"])
    to_send = [c for c in cambios if _ORDER[c.max_severity] <= minimum]
    status, error, sent = "skipped_no_changes", None, False
    digest = build_digest(client_name, date_label(day), to_send, urls_checked=urls_checked, errors=n_err,
                          detail_url=changes_url(client_id), notes=notes)
    if digest is not None:
        delivery = await post(webhook, digest["text"], digest["blocks"])
        status, error, sent = ("sent" if delivery.ok else "failed"), delivery.error, delivery.ok
        if delivery.revoked:
            await _mark_revoked(session_factory, client_id)
            return "revoked", delivery.error, False

    # Resumen del barrido completo: aunque no haya cambios. Es lo que convierte
    # el silencio en una señal fiable. Va después del detalle.
    if completo and cfg.sweep_summary_to_slack:
        n_critical = sum(1 for c in cambios for i in c.items if i["severity"] == "critical")
        summary = build_summary(client_name, date_label(day), urls_checked=urls_checked,
                                urls_changed=len(cambios), n_critical=n_critical, errors=n_err, trigger=trigger,
                                detail_url=changes_url(client_id), notes=notes)
        delivery = await post(webhook, summary["text"], summary["blocks"])
        if delivery.revoked:
            await _mark_revoked(session_factory, client_id)
            return "revoked", delivery.error, sent
        if status == "skipped_no_changes":
            status = "summary_sent" if delivery.ok else "failed"
            error = None if delivery.ok else delivery.error
        sent = sent or delivery.ok
    return status, error, sent


async def _mark_revoked(session_factory, client_id: int) -> None:
    """El webhook ya no existe en Slack: se apaga, como en el monitor de caídas."""
    async with session_factory() as db:
        await db.execute(update(ClientWebSettings).where(ClientWebSettings.client_id == client_id).values(
            slack_enabled=False, slack_revoked_at=datetime.now(UTC),
        ))
        await db.commit()


async def sweep_client(
    session_factory, client_id: int, *, trigger: str = "scheduler", watch_ids: list | None = None,
    notify: bool = True, completo: bool = False, fetcher: Fetcher = fetch, post: Poster = post_message,
    now: datetime | None = None, sleep: Sleeper = asyncio.sleep,
) -> dict:
    """Barre un cliente. Devuelve un resumen.

    ``completo`` = se han mirado TODAS sus URLs (el diario o "comprobar todas"):
    sólo entonces va el resumen a Slack. ``notify=False`` = comprobar URLs
    sueltas, alguien ya está mirando la pantalla.
    """
    started = now or datetime.now(UTC)
    day = local_date(started)

    async with session_factory() as db:
        # Sólo el nombre: ``Client`` arrastra muchas relaciones ``selectin``.
        client_row = (await db.execute(select(Client.name).where(Client.id == client_id))).one_or_none()
        if client_row is None:
            return {"client_id": client_id, "watches": 0, "notify": "sin_cliente"}
        client_name = client_row.name or f"Cliente #{client_id}"
        web = await db.get(ClientWebSettings, client_id, populate_existing=True)
        cfg = effective_settings(web)
        web_state = slack_state(web)
        webhook_enc = web.slack_webhook_url if web is not None else None
        query = select(WebWatch).where(WebWatch.client_id == client_id, watched_clause()).order_by(WebWatch.url)
        if watch_ids is not None:
            query = query.where(WebWatch.id.in_(list(watch_ids)))
        watches = [WatchRow.of(w) for w in (await db.scalars(query)).all()]
        if not watches:
            await db.commit()
            return {"client_id": client_id, "watches": 0, "changes": 0, "notify": "sin_watches"}

        run_id = uuid.uuid4()
        db.add(WebSweepRun(id=run_id, client_id=client_id, run_date=day, trigger=trigger, status="running",
                           started_at=started, watches_total=len(watches)))
        try:
            await db.flush()
        except IntegrityError:
            # Sólo choca el PROGRAMADO (índice único parcial): ya corrió hoy.
            # Lo manual nunca choca (lección 0bis de Vigil).
            await db.rollback()
            logger.info("Webs: el barrido programado del cliente %s ya corrió hoy", client_id)
            return {"client_id": client_id, "skipped": "ya_ejecutado_hoy"}
        # "Comprobando", para que la interfaz lo enseñe (también las nunca miradas).
        mark = pg_insert(WebWatchState).values([
            {"watch_id": w.id, "client_id": client_id, "checking_since": started, "updated_at": started}
            for w in watches
        ])
        await db.execute(mark.on_conflict_do_update(
            index_elements=[WebWatchState.watch_id], set_={"checking_since": started},
        ))
        await db.commit()

    n_ok = n_err = 0
    cambios: list[DigestChange] = []
    notes: list[str] = []
    cut: dict[str, tuple[int, int]] = {}
    status = "failed"
    # Si el barrido se rompe antes de avisar, queda NULL: ni "enviado" ni un motivo inventado.
    notify_status = "no_procede" if not notify else (None if web_state == "ready" else web_state)
    notify_error, notified = None, False
    try:
        results = await fetch_many(
            [(w.id, w.url) for w in watches], max_concurrency=cfg.max_concurrency,
            timeout_s=cfg.request_timeout_s, delay_ms=cfg.crawl_delay_ms, user_agent=cfg.user_agent,
            fetcher=fetcher, sleep=sleep,
        )
        checked_at = now or datetime.now(UTC)
        cut = circuit_open_hosts(results, watches)
        if cut:
            async with session_factory() as db:
                uptime = await uptime_by_host(db, client_id)
                for host, (failed, total) in cut.items():
                    note = circuit_note(host, failed, total, uptime.get(_bare(host)))
                    notes.append(note)
                    logger.warning("Webs: circuito abierto para %s (cliente %s)", host, client_id)
                    db.add(WebRunError(run_id=run_id, client_id=client_id, watch_id=None,
                                       kind="host_circuit_open", message=note[:500], created_at=checked_at))
                await db.commit()

        for watch in watches:
            result = results.get(watch.id)
            # Con el circuito abierto NO se clasifica: serían decenas de "página
            # caída" falsas por un bloqueo. Tampoco se toca su estado.
            if host_of(watch.url) in cut and unreachable(result):
                n_err += 1
                continue
            try:
                outcome = await process_watch(session_factory, watch=watch, cfg=cfg, result=result,
                                              run_id=run_id, now=checked_at)
            except Exception as exc:  # noqa: BLE001 — una URL nunca tumba el barrido
                logger.error("Webs: no se pudo guardar la URL %s (%s)", watch.id, type(exc).__name__)
                outcome = WatchOutcome(watch.id, ok=False, error=f"Error interno: {type(exc).__name__}",
                                       error_kind="storage")
            if outcome.ok:
                n_ok += 1
                if outcome.changed and not watch.muted:
                    cambios.append(DigestChange(
                        url=watch.url, label=watch.label, max_severity=max_severity(outcome.items),
                        change_id=str(outcome.change_id) if outcome.change_id else None,
                        items=[{"kind": i.kind, "field": i.field, "severity": i.severity,
                                "rule_code": i.rule_code, "before_val": i.before_val,
                                "after_val": i.after_val, "detail": i.detail} for i in outcome.items],
                    ))
            else:
                n_err += 1
                try:
                    async with session_factory() as db:
                        db.add(WebRunError(run_id=run_id, client_id=client_id, watch_id=watch.id,
                                           kind=(outcome.error_kind or "error")[:32],
                                           message=(outcome.error or "")[:500],
                                           status_code=result.status_code if result else None,
                                           created_at=checked_at))
                        await db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Webs: no se pudo anotar el error de %s (%s)", watch.id, type(exc).__name__)

        status = "partial" if n_err else "done"
        if notify:
            # Sin transacción abierta mientras se habla con Slack. Un fallo aquí
            # no invalida el barrido: los cambios ya están guardados.
            try:
                notify_status, notify_error, notified = await _notify(
                    session_factory, client_id=client_id, client_name=client_name, web_state=web_state,
                    webhook_enc=webhook_enc, cfg=cfg, cambios=cambios, urls_checked=len(watches), n_err=n_err,
                    notes=notes, trigger=trigger, completo=completo, day=day, post=post,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Webs: el aviso a Slack del cliente %s falló (%s)", client_id, type(exc).__name__)
                notify_status, notify_error = "failed", f"Error interno: {type(exc).__name__}"
    finally:
        # La marca de "comprobando" se limpia SIEMPRE, también si el barrido acabó
        # a medias: si no, la interfaz se quedaría girando.
        finished = datetime.now(UTC) if now is None else now
        try:
            async with session_factory() as db:
                await db.execute(update(WebWatchState).where(
                    WebWatchState.watch_id.in_([w.id for w in watches]),
                ).values(checking_since=None))
                await db.execute(update(WebSweepRun).where(WebSweepRun.id == run_id).values(
                    status=status, finished_at=finished, watches_done=n_ok, watches_error=n_err,
                    changes_found=len(cambios), notified_at=finished if notified else None,
                    notify_status=notify_status, notify_error=(notify_error or None) and notify_error[:500],
                ))
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — lo recoge ``reap_orphans`` en el siguiente ciclo
            logger.error("Webs: no se pudo cerrar el barrido %s (%s)", run_id, type(exc).__name__)

    return {
        "client_id": client_id, "run_id": str(run_id), "watches": len(watches), "ok": n_ok, "errors": n_err,
        "changes": len(cambios), "notify": notify_status, "hosts_cut": sorted(cut),
    }


# ---------------------------------------------------------------------------
# El ciclo del job ``web_sweep``
# ---------------------------------------------------------------------------


def sweep_start_time() -> dtime:
    """``WEB_SWEEP_LOCAL_TIME`` (HH:MM, hora de la agencia). Mal escrita = 06:30."""
    try:
        hours, minutes = (int(x) for x in (settings.WEB_SWEEP_LOCAL_TIME or "").split(":", 1))
        return dtime(hours, minutes)
    except (ValueError, TypeError):
        logger.error("WEB_SWEEP_LOCAL_TIME no es HH:MM (%r); se usa 06:30", settings.WEB_SWEEP_LOCAL_TIME)
        return dtime(6, 30)


@dataclass
class CycleResult:
    reaped_runs: int = 0
    reaped_marks: int = 0
    manual: list[dict] = field(default_factory=list)
    scheduled: dict | None = None
    calendar_skipped: list[tuple[int, str]] = field(default_factory=list)
    failed: int = 0


async def manual_requests(db) -> list[tuple[int, list[uuid.UUID], datetime]]:
    """Clientes con "Comprobar ahora" pendiente: (cliente, URLs, marca más reciente)."""
    rows = (await db.execute(
        select(WebWatch.client_id, WebWatch.id, WebWatch.check_requested_at)
        .join(Client, Client.id == WebWatch.client_id)
        .where(WebWatch.check_requested_at.is_not(None), watched_clause(), monitored_clients_clause())
        .order_by(WebWatch.check_requested_at, WebWatch.id)
    )).all()
    grouped: dict[int, tuple[list, datetime]] = {}
    for client_id, watch_id, requested in rows:
        ids, latest = grouped.get(client_id, ([], requested))
        ids.append(watch_id)
        grouped[client_id] = (ids, max(latest, requested))
    return [(cid, ids, latest) for cid, (ids, latest) in grouped.items()]


async def scheduled_candidates(db, day: date) -> list[int]:
    """Clientes activos con alguna URL vigilada y sin barrido programado hoy."""
    return list((await db.scalars(
        select(Client.id).where(
            monitored_clients_clause(),
            exists().where(WebWatch.client_id == Client.id, watched_clause()),
            ~exists().where(WebSweepRun.client_id == Client.id, WebSweepRun.trigger == "scheduler",
                            WebSweepRun.run_date == day),
        ).order_by(Client.id)
    )).all())


async def run_cycle(
    session_factory, *, now: datetime | None = None, fetcher: Fetcher = fetch, post: Poster = post_message,
    sleep: Sleeper = asyncio.sleep, clock: Callable[[], float] = time.monotonic,
) -> CycleResult:
    """Una pasada del job: recoger huérfanos, lo pedido a mano y, si toca, el
    barrido diario de UN cliente (el índice único parcial impide repetirlo)."""
    result = CycleResult()
    began = clock()
    result.reaped_runs, result.reaped_marks = await reap_orphans(session_factory, now=now)

    # 1. Lo pedido a mano primero: alguien está mirando la pantalla.
    async with session_factory() as db:
        pending = await manual_requests(db)
        await db.commit()
    for client_id, ids, latest in pending:
        if clock() - began > MANUAL_BUDGET_SECONDS:
            break
        try:
            async with session_factory() as db:
                active = set((await db.scalars(select(WebWatch.id).where(
                    WebWatch.client_id == client_id, watched_clause(),
                ))).all())
                await db.commit()
            # Todas las URLs del cliente = "comprobar todas": avisa y resume en Slack.
            completo = active == set(ids)
            result.manual.append(await sweep_client(
                session_factory, client_id, trigger="manual", watch_ids=ids, notify=completo,
                completo=completo, fetcher=fetcher, post=post, now=now, sleep=sleep,
            ))
        except Exception as exc:  # noqa: BLE001 — un cliente no tumba a los demás
            result.failed += 1
            logger.error("Webs: la comprobación del cliente %s falló (%s)", client_id, type(exc).__name__)
        finally:
            # Se consume la petición aunque falle (si no, se repetiría cada
            # minuto); lo pedido DURANTE el barrido se conserva.
            try:
                async with session_factory() as db:
                    await db.execute(update(WebWatch).where(
                        WebWatch.id.in_(ids), WebWatch.check_requested_at <= latest,
                    ).values(check_requested_at=None))
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("Webs: no se pudo limpiar la petición del cliente %s (%s)",
                             client_id, type(exc).__name__)

    # 2. El diario: a partir de la hora configurada, UN cliente por ciclo.
    instant = now or datetime.now(UTC)
    local = instant.astimezone(business_zone())
    if local.time() < sweep_start_time() or clock() - began > SCHEDULED_START_LIMIT:
        return result
    day = local.date()
    async with session_factory() as db:
        candidates = await scheduled_candidates(db, day)
        await db.commit()
    for client_id in candidates:
        async with session_factory() as db:
            cfg = effective_settings(await db.get(ClientWebSettings, client_id, populate_existing=True))
            await db.commit()
        # El calendario sólo aplica al AUTOMÁTICO: "comprobar todas" un domingo vale.
        due, reason = toca_barrido(cfg.calendar(), day)
        if not due:
            result.calendar_skipped.append((client_id, reason))
            continue
        try:
            result.scheduled = await sweep_client(
                session_factory, client_id, trigger="scheduler", notify=True, completo=True,
                fetcher=fetcher, post=post, now=now, sleep=sleep,
            )
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            logger.error("Webs: el barrido diario del cliente %s falló (%s)", client_id, type(exc).__name__)
        break
    return result


async def purge_old_runs(db, *, now: datetime | None = None, days: int = 180) -> int:
    """Retención: barridos de más de ``days`` días (sus errores van en cascada; los
    cambios y capturas se quedan con ``run_id`` a NULL)."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    result = await db.execute(delete(WebSweepRun).where(WebSweepRun.started_at < cutoff))
    return result.rowcount or 0


def stale_mark_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(minutes=STALE_MARK_MINUTES)
