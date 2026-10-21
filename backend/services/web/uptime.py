"""Monitor de caídas de las webs de los clientes (Webs fase 1, job ``uptime``).

Qué cuenta como qué (``classify``)
----------------------------------
- ``up``: 2xx/3xx (tras seguir hasta 5 redirecciones revalidadas).
- ``blocked``: 401/403/429 o un desafío de Cloudflare. NO es una caída: la web
  responde, pero no a nosotros (WAF, User-Agent…). Si dura más de
  ``UPTIME_BLOCKED_ALERT_MINUTES`` se abre una "caída" de tipo ``blocked`` que
  sólo es un aviso (la bandeja, no Slack): "no podemos comprobarla".
- ``down``: 5xx, 404/410 y el resto de 4xx, timeout, DNS, conexión rechazada o
  cortada, TLS, demasiadas redirecciones o una dirección no pública.

Máquina de estados (``advance``)
--------------------------------
Sano: se mira cada ``UPTIME_INTERVAL_SECONDS`` (300 s). Primer fallo →
``suspect`` y se vuelve a mirar a los ``UPTIME_RECHECK_SECONDS`` (60 s).
``UPTIME_FAILURES_TO_ALERT`` (2) ciclos fallidos seguidos → ``down``: se abre la
caída (``confirmed_at``) con su aviso. Se cierra tras ``UPTIME_RECOVERIES_TO_CLOSE``
(2) ciclos buenos (``ended_at``) y avisa de la recuperación con la duración.
Dentro de cada ciclo, un fallo se reintenta una vez a los 5-10 s.

Contra falsas alarmas
---------------------
- Canario: al empezar, si NINGUNA de ``UPTIME_CANARY_URLS`` responde, el
  problema es nuestra red: no se mira nada y el job falla con
  ``provider_unavailable``.
- Correlación: si en un mismo ciclo fallan por red (sin respuesta HTTP) al
  menos 3 hosts distintos y son la mitad o más de los mirados, también es
  nuestra red: esos fallos no avanzan contadores (se vuelve a mirar en 60 s).

Cortesía: cada host se recorre en serie; hosts distintos van en paralelo
(máximo 8 a la vez). User-Agent del cliente (``client_web_settings``) o el de
``headers.py``.

Slack como outbox: la caída se guarda con su aviso ``pending`` en la misma
transacción que el estado; después se publica (``uptime_notify``) y se anota.
Lo pendiente se reintenta al empezar cada ciclo.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import and_, select, text

from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, WebOutage, WebUptimeProbe, WebUptimeState, WebUptimeTarget,
)
from backend.services.temporal import business_zone
from backend.services.web.safe_http import FetchResult, SSRFError, check_url_syntax, fetch

logger = logging.getLogger(__name__)

MAX_CONCURRENCY = 8
RETRY_DELAY_SECONDS = (5.0, 10.0)
CORRELATION_MIN_HOSTS = 3
CORRELATION_SHARE = 0.5
# El job tiene 150 s; lo que no termine en este tiempo se mira en el siguiente.
PROBE_BUDGET_SECONDS = 110.0
MAX_TARGETS_PER_CYCLE = 300
PROBE_TIMEOUT_SECONDS = 15.0
CONNECT_TIMEOUT_SECONDS = 10.0
_BLOCK_STATUSES = frozenset({401, 403, 429})
# Errores sin respuesta HTTP: los únicos que pueden ser culpa de nuestra red.
NETWORK_ERRORS = frozenset({"timeout", "dns", "connect", "tls"})

Fetcher = Callable[..., Awaitable[FetchResult]]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class UptimeConfig:
    interval: int = 300
    recheck: int = 60
    failures_to_alert: int = 2
    recoveries_to_close: int = 2
    blocked_minutes: int = 60

    @classmethod
    def from_settings(cls) -> "UptimeConfig":
        return cls(
            interval=max(60, settings.UPTIME_INTERVAL_SECONDS),
            recheck=max(30, settings.UPTIME_RECHECK_SECONDS),
            failures_to_alert=max(1, settings.UPTIME_FAILURES_TO_ALERT),
            recoveries_to_close=max(1, settings.UPTIME_RECOVERIES_TO_CLOSE),
            blocked_minutes=max(1, settings.UPTIME_BLOCKED_ALERT_MINUTES),
        )


# ── Clasificación ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Probe:
    outcome: str  # up | down | blocked
    cause: str | None  # http_503, timeout, dns, challenge…
    status_code: int | None
    response_ms: int | None


def _is_challenge(result: FetchResult) -> bool:
    """Desafío de Cloudflare (``cf-mitigated: challenge`` o su página "Just a moment")."""
    if result.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if "cloudflare" not in result.headers.get("server", "").lower():
        return False
    head = result.body[:16384].lower()
    return b"challenge-platform" in head or b"just a moment" in head or b"cf-chl" in head


def classify(result: FetchResult) -> Probe:
    code = result.status_code
    if result.error or code is None:
        return Probe("down", result.error or "error", code, result.elapsed_ms)
    if code in _BLOCK_STATUSES:
        return Probe("blocked", "challenge" if _is_challenge(result) else f"http_{code}", code, result.elapsed_ms)
    if code >= 400 and _is_challenge(result):
        return Probe("blocked", "challenge", code, result.elapsed_ms)
    if 200 <= code < 400:
        return Probe("up", None, code, result.elapsed_ms)
    return Probe("down", f"http_{code}", code, result.elapsed_ms)


_CAUSES = {
    "timeout": "no responde a tiempo",
    "dns": "el dominio no resuelve (DNS)",
    "connect": "conexión rechazada o cortada",
    "tls": "error de certificado o TLS",
    "unsafe": "la dirección apunta a una red no pública o a un puerto no permitido",
    "redirects": "demasiadas redirecciones",
    "challenge": "desafío anti-bots (Cloudflare)",
    "error": "error desconocido",
}


def cause_label(cause: str | None) -> str | None:
    if not cause:
        return None
    if cause.startswith("http_"):
        return f"error HTTP {cause[5:]}"
    return _CAUSES.get(cause, cause)


def format_duration(delta: timedelta) -> str:
    minutes = max(1, int(delta.total_seconds() // 60))
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} min"


def local_when(instant: datetime) -> str:
    """``21/10 a las 10:02`` en hora de la agencia."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    local = instant.astimezone(business_zone())
    return f"{local:%d/%m} a las {local:%H:%M}"


async def probe(
    url: str, *, user_agent: str | None = None, retry: bool = True,
    fetcher: Fetcher = fetch, sleep: Sleeper = asyncio.sleep,
) -> Probe:
    """Mira una URL; si falla, vuelve a mirar una vez a los 5-10 s (mismo ciclo)."""
    result = classify(await fetcher(
        url, user_agent=user_agent, timeout=PROBE_TIMEOUT_SECONDS, connect_timeout=CONNECT_TIMEOUT_SECONDS,
    ))
    if result.outcome != "down" or not retry:
        return result
    await sleep(random.uniform(*RETRY_DELAY_SECONDS))  # noqa: S311 — no es criptografía
    return classify(await fetcher(
        url, user_agent=user_agent, timeout=PROBE_TIMEOUT_SECONDS, connect_timeout=CONNECT_TIMEOUT_SECONDS,
    ))


# ── Máquina de estados (pura) ────────────────────────────────────────


@dataclass(frozen=True)
class Snapshot:
    status: str = "unknown"
    failures: int = 0
    successes: int = 0
    failing_since: datetime | None = None
    blocked_since: datetime | None = None
    status_since: datetime | None = None


@dataclass(frozen=True)
class Transition:
    state: Snapshot
    next_check_at: datetime
    open_kind: str | None = None  # abrir una caída de este tipo
    open_started_at: datetime | None = None
    close: bool = False  # cerrar la caída abierta (antes de abrir otra)


def advance(prev: Snapshot, outcome: str, now: datetime, open_kind: str | None, cfg: UptimeConfig) -> Transition:
    """Siguiente estado tras un resultado. ``open_kind``: tipo de la caída abierta, si hay."""
    failures, successes = prev.failures, prev.successes
    failing_since, blocked_since = prev.failing_since, prev.blocked_since
    close, new_kind, started = False, None, None

    if outcome == "up":
        failures, failing_since, blocked_since = 0, None, None
        if open_kind == "down":
            successes += 1
            if successes >= cfg.recoveries_to_close:
                close, successes, status = True, 0, "up"
            else:
                status = "down"
        else:
            close = open_kind == "blocked"
            successes, status = 0, "up"
    elif outcome == "down":
        successes, blocked_since = 0, None
        failures += 1
        failing_since = failing_since or now
        if open_kind == "down":
            status = "down"
        elif failures >= cfg.failures_to_alert:
            close = open_kind == "blocked"
            new_kind, started, status = "down", failing_since, "down"
        else:
            status = "suspect"
    else:  # blocked: la web responde, pero no a nosotros
        failures, failing_since = 0, None
        if open_kind == "down":
            # Responder (aunque sea con un 403) es que el servidor está vivo.
            successes += 1
            if successes >= cfg.recoveries_to_close:
                close, successes, status, blocked_since = True, 0, "blocked", now
            else:
                status = "down"
        else:
            successes = 0
            blocked_since = blocked_since or now
            status = "blocked"
            if open_kind is None and now - blocked_since >= timedelta(minutes=cfg.blocked_minutes):
                new_kind, started = "blocked", blocked_since

    state = Snapshot(
        status=status, failures=failures, successes=successes, failing_since=failing_since,
        blocked_since=blocked_since, status_since=prev.status_since if status == prev.status else now,
    )
    wait = cfg.recheck if status in ("suspect", "down") else cfg.interval
    return Transition(state, now + timedelta(seconds=wait), new_kind, started, close)


# ── Ciclo del job ────────────────────────────────────────────────────


@dataclass(frozen=True)
class DueTarget:
    id: int
    url: str
    user_agent: str | None
    host: str


@dataclass
class CycleResult:
    due: int = 0
    probed: int = 0
    applied: int = 0
    opened: int = 0
    closed: int = 0
    network_issue: bool = False
    canary_failed: bool = False
    failed: int = 0
    slack: dict = field(default_factory=dict)


def canary_urls() -> list[str]:
    return [u.strip() for u in (settings.UPTIME_CANARY_URLS or "").split(",") if u.strip()]


async def connectivity_ok(urls: list[str], *, fetcher: Fetcher = fetch) -> bool:
    """Basta con que UNA URL canario dé cualquier respuesta HTTP."""
    if not urls:
        return True
    results = await asyncio.gather(*(
        fetcher(url, timeout=10.0, connect_timeout=5.0) for url in urls
    ), return_exceptions=True)
    return any(isinstance(r, FetchResult) and r.status_code is not None for r in results)


async def _ensure_states(db) -> None:
    """Un objetivo sin fila de estado (p. ej. creado a mano) entra en el siguiente ciclo."""
    await db.execute(text(
        "INSERT INTO web_uptime_state (target_id) SELECT t.id FROM web_uptime_targets t "
        "WHERE NOT EXISTS (SELECT 1 FROM web_uptime_state s WHERE s.target_id = t.id) "
        "ON CONFLICT (target_id) DO NOTHING"
    ))


def monitored_clause():
    """Sólo objetivos activos de clientes activos y externos."""
    return and_(
        WebUptimeTarget.is_active.is_(True),
        Client.status == ClientStatus.active,
        Client.is_internal.is_(False),
    )


async def due_targets(db, now: datetime) -> list[DueTarget]:
    rows = (await db.execute(
        select(WebUptimeTarget.id, WebUptimeTarget.url, ClientWebSettings.user_agent)
        .join(WebUptimeState, WebUptimeState.target_id == WebUptimeTarget.id)
        .join(Client, Client.id == WebUptimeTarget.client_id)
        .outerjoin(ClientWebSettings, ClientWebSettings.client_id == WebUptimeTarget.client_id)
        .where(monitored_clause(), WebUptimeState.next_check_at <= now)
        .order_by(WebUptimeState.next_check_at, WebUptimeTarget.id)
        .limit(MAX_TARGETS_PER_CYCLE)
    )).all()
    out = []
    for row in rows:
        try:
            host = check_url_syntax(row.url)
        except SSRFError:
            host = row.url  # se mira igual: fetch lo rechaza y queda como caída "unsafe"
        out.append(DueTarget(row.id, row.url, row.user_agent, host))
    return out


async def probe_all(
    targets: list[DueTarget], *, fetcher: Fetcher = fetch, sleep: Sleeper = asyncio.sleep,
    budget: float = PROBE_BUDGET_SECONDS,
) -> dict[int, Probe]:
    """Cada host en serie, hosts distintos en paralelo (máx. 8). Lo que no acabe
    dentro de ``budget`` se queda sin resultado y se mira en el siguiente ciclo."""
    by_host: dict[str, list[DueTarget]] = {}
    for target in targets:
        by_host.setdefault(target.host, []).append(target)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: dict[int, Probe] = {}

    async def limited_fetch(*args, **kwargs):
        async with semaphore:
            return await fetcher(*args, **kwargs)

    async def walk(queue: list[DueTarget]) -> None:
        for target in queue:
            # El semáforo sólo cubre cada petición: la espera del reintento no
            # bloquea a otros hosts.
            results[target.id] = await probe(
                target.url, user_agent=target.user_agent, fetcher=limited_fetch, sleep=sleep,
            )

    tasks = [asyncio.create_task(walk(queue)) for queue in by_host.values()]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=budget)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    return results


def network_problem(targets: list[DueTarget], results: dict[int, Probe]) -> bool:
    """¿Fallan por red tantos hosts a la vez que el problema es nuestro?"""
    hosts = {t.host for t in targets if t.id in results}
    failing = {t.host for t in targets if t.id in results
               and results[t.id].outcome == "down" and results[t.id].cause in NETWORK_ERRORS}
    return len(failing) >= CORRELATION_MIN_HOSTS and len(failing) >= CORRELATION_SHARE * len(hosts)


def _snapshot(row: WebUptimeState) -> Snapshot:
    return Snapshot(
        status=row.status, failures=row.consecutive_failures or 0, successes=row.consecutive_successes or 0,
        failing_since=row.failing_since, blocked_since=row.blocked_since, status_since=row.status_since,
    )


def slack_eligible(web: ClientWebSettings | None) -> bool:
    return bool(web and web.slack_enabled and web.slack_webhook_url and web.downtime_to_slack
                and web.slack_revoked_at is None)


async def apply_probe(db, target_id: int, url: str, result: Probe, now: datetime, cfg: UptimeConfig) -> dict:
    """Guarda un resultado: estado, sondeo y caída. No hace commit."""
    target = await db.get(WebUptimeTarget, target_id)
    # El objetivo pudo cambiar o desactivarse mientras se miraba: no aplicar.
    if target is None or not target.is_active or target.url != url:
        return {"applied": False}
    state = (await db.execute(
        select(WebUptimeState).where(WebUptimeState.target_id == target_id).with_for_update()
    )).scalar_one_or_none()
    if state is None:
        state = WebUptimeState(target_id=target_id, status="unknown", next_check_at=now)
        db.add(state)
    open_outage = (await db.execute(
        select(WebOutage).where(WebOutage.target_id == target_id, WebOutage.ended_at.is_(None)).with_for_update()
    )).scalar_one_or_none()
    transition = advance(_snapshot(state), result.outcome, now, open_outage.kind if open_outage else None, cfg)

    new = transition.state
    state.status, state.status_since = new.status, new.status_since
    state.consecutive_failures, state.consecutive_successes = new.failures, new.successes
    state.failing_since, state.blocked_since = new.failing_since, new.blocked_since
    state.last_checked_at, state.last_outcome = now, result.outcome
    state.last_status_code, state.last_error = result.status_code, result.cause
    state.last_response_ms = result.response_ms
    state.next_check_at = transition.next_check_at
    db.add(WebUptimeProbe(
        target_id=target_id, checked_at=now, outcome=result.outcome,
        status_code=result.status_code, error=result.cause, response_ms=result.response_ms,
    ))

    opened = closed = 0
    if transition.close and open_outage is not None:
        open_outage.ended_at = now
        open_outage.slack_recovery_status = (
            "pending" if open_outage.slack_down_status in ("pending", "sent") else "skipped"
        )
        closed = 1
        await db.flush()  # libera el índice único de "una caída abierta"
    if transition.open_kind:
        web = await db.get(ClientWebSettings, target.client_id)
        db.add(WebOutage(
            target_id=target_id, kind=transition.open_kind,
            started_at=transition.open_started_at or now, confirmed_at=now,
            cause=result.cause, status_code=result.status_code,
            # Slack sólo para caídas: un bloqueo es un aviso interno.
            slack_down_status="pending" if transition.open_kind == "down" and slack_eligible(web) else "skipped",
        ))
        opened = 1
    await db.flush()
    return {"applied": True, "opened": opened, "closed": closed}


async def run_cycle(
    session_factory, *, now: datetime | None = None, fetcher: Fetcher = fetch,
    sleep: Sleeper = asyncio.sleep, post=None, cfg: UptimeConfig | None = None,
) -> CycleResult:
    """Una pasada del job: reintentos de Slack, canario, sondeos, estado y avisos."""
    from backend.services.web import uptime_notify

    cfg = cfg or UptimeConfig.from_settings()
    result = CycleResult()
    post_kwargs = {"post": post} if post else {}
    result.slack = await uptime_notify.deliver_pending(session_factory, **post_kwargs)

    fixed_now = now
    async with session_factory() as db:
        await _ensure_states(db)
        await db.commit()
        targets = await due_targets(db, fixed_now or datetime.now(UTC))
    result.due = len(targets)
    if not targets:
        return result

    if not await connectivity_ok(canary_urls(), fetcher=fetcher):
        result.canary_failed = True
        logger.warning("Uptime: el canario no responde; ciclo saltado (%d objetivos)", len(targets))
        return result

    probes = await probe_all(targets, fetcher=fetcher, sleep=sleep)
    result.probed = len(probes)
    skip_failures = network_problem(targets, probes)
    result.network_issue = skip_failures
    if skip_failures:
        logger.warning("Uptime: fallos de red correlacionados; no avanzan contadores")
    # El instante de la comprobación es el de después de mirar, no el de empezar.
    checked_at = fixed_now or datetime.now(UTC)
    for target in targets:
        probe_result = probes.get(target.id)
        if probe_result is None:
            continue
        async with session_factory() as db:
            try:
                if skip_failures and probe_result.outcome == "down" and probe_result.cause in NETWORK_ERRORS:
                    state = await db.get(WebUptimeState, target.id)
                    if state is not None:
                        state.next_check_at = checked_at + timedelta(seconds=cfg.recheck)
                    await db.commit()
                    continue
                applied = await apply_probe(db, target.id, target.url, probe_result, checked_at, cfg)
                await db.commit()
            except Exception as exc:  # noqa: BLE001 — un objetivo no tumba el ciclo
                await db.rollback()
                result.failed += 1
                logger.error("Uptime: no se pudo guardar target_id=%s (%s)", target.id, type(exc).__name__)
                continue
        if applied["applied"]:
            result.applied += 1
            result.opened += applied["opened"]
            result.closed += applied["closed"]

    if result.opened or result.closed:
        sent = await uptime_notify.deliver_pending(session_factory, **post_kwargs)
        result.slack = {k: result.slack.get(k, 0) + v for k, v in sent.items()}
    return result
