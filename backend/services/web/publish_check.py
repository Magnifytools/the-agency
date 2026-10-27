"""Revisión tras publicar (job ``publish_checks``, lock 19).

Cuando una tarea con enlace (``Task.link_url``) se completa, se mira esa URL
FUERA de la petición que la cierra: el cierre nunca espera ni falla por esto.
El job encuentra cada minuto las tareas completadas hace poco sin revisión de
esa finalización (o con el enlace cambiado) y las que tocan reintento.

Qué se mira (``safe_http.fetch`` + ``extractor.extract_seo``, en un hilo):
responde 2xx, es indexable (sin ``noindex``/``none`` en meta robots ni en
``X-Robots-Tag``), tiene canonical (y apunta a sí misma), title y meta
description.

Sólo se revisa un enlace de la web del cliente de la tarea (su ``website``,
``gsc_url`` o sus URLs vigiladas, con o sin ``www.`` y sus subdominios): un
Google Doc o un Figma no son una página publicada. Lo demás queda ``skipped``
con el motivo, para que la ficha diga por qué no se revisó.

Reintentos acotados: un fallo de red, un 5xx o un 404 (la página puede tardar
en salir de caché) se reintenta a los 2, 10 y 30 minutos; después queda como
resultado. Si algo falla, se avisa una vez al responsable de la tarea en la
campana (``task_publish_check``, clave por finalización).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select

from backend.db.models import (
    Client, Notification, Project, Task, TaskPublishCheck, TaskStatus, WebUptimeTarget, WebWatch,
)
from backend.services.web import extractor
from backend.services.web.safe_http import SSRFError, FetchResult, check_url_syntax, fetch
from backend.services.web.sweep import decode_body
from backend.services.web.uptime import cause_label

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "task_publish_check"
WINDOW = timedelta(days=3)          # tareas completadas hace como mucho esto
RETRY_DELAYS = (timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30))
MAX_PER_CYCLE = 20
MAX_BYTES = 1024 * 1024
TIMEOUT_S = 20.0
_RETRYABLE_STATUS = frozenset({404, 500, 502, 503, 504})

SKIP_REASONS = {
    "no_client": "La tarea no tiene cliente: no sabemos cuál es su web.",
    "not_web": "El enlace no es una dirección web pública.",
    "other_site": "El enlace no es de la web del cliente (por ejemplo, un documento).",
}


def bare_host(value: str | None) -> str | None:
    """Host sin ``www.`` de una URL, de un dominio suelto o de ``sc-domain:``."""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("sc-domain:"):
        host = value[len("sc-domain:"):]
    else:
        host = urlparse(value if "://" in value else f"https://{value}").hostname or ""
    host = host.lower().rstrip(".").removeprefix("www.")
    return host or None


def same_site(link_host: str, site_hosts: set[str]) -> bool:
    return any(link_host == h or link_host.endswith("." + h) or h.endswith("." + link_host) for h in site_hosts)


async def client_hosts(db, client_id: int) -> set[str]:
    client = (await db.execute(select(Client.website, Client.gsc_url).where(Client.id == client_id))).one_or_none()
    hosts = set()
    if client is not None:
        hosts.update(h for h in (bare_host(client.website), bare_host(client.gsc_url)) if h)
    urls = (await db.scalars(select(WebUptimeTarget.url).where(WebUptimeTarget.client_id == client_id))).all()
    urls += (await db.scalars(select(WebWatch.url).where(WebWatch.client_id == client_id))).all()
    hosts.update(h for h in (bare_host(u) for u in urls) if h)
    return hosts


def _norm_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}{path}"


def evaluate(result: FetchResult) -> tuple[str, list[dict]]:
    """(``ok`` | ``problems``, comprobaciones). CPU (lxml): llamar en un hilo."""
    code = result.status_code
    redirected = result.redirects > 0
    http_ok = code is not None and 200 <= code < 300
    detail = f"Responde {code}" + (f" tras redirigir a {result.final_url}" if redirected else "")
    checks = [{"code": "http", "label": "La página responde", "ok": http_ok, "detail": detail}]
    if not http_ok:
        return "problems", checks
    tree = extractor.parse(decode_body(result))
    seo = extractor.extract_seo(tree, base_url=result.final_url, final_url=result.final_url,
                                status_code=code, headers=result.headers)
    blocking = {"noindex", "none"}
    source = [label for label, raw in (("meta robots", seo["meta_robots"]), ("cabecera X-Robots-Tag", seo["x_robots_tag"]))
              if blocking & {d.strip().lower() for d in (raw or "").split(",")}]
    noindex = bool(blocking & set(seo["robots_directives"]))
    checks.append({"code": "indexable", "label": "Google puede indexarla", "ok": not noindex,
                   "detail": f"Lleva noindex ({', '.join(source) or 'robots'})" if noindex else "Sin noindex"})
    canonical = seo["canonical"]
    if not canonical:
        checks.append({"code": "canonical", "label": "Tiene canonical", "ok": False, "detail": "No tiene etiqueta canonical"})
    elif _norm_url(canonical) != _norm_url(result.final_url):
        checks.append({"code": "canonical", "label": "Tiene canonical", "ok": False,
                       "detail": f"El canonical apunta a otra URL: {canonical}"[:500]})
    else:
        checks.append({"code": "canonical", "label": "Tiene canonical", "ok": True, "detail": canonical[:500]})
    title = seo["title"]
    checks.append({"code": "title", "label": "Tiene title", "ok": bool(title),
                   "detail": title[:300] if title else "Sin title"})
    description = seo["meta_description"]
    checks.append({"code": "meta_description", "label": "Tiene meta description", "ok": bool(description),
                   "detail": description[:300] if description else "Sin meta description"})
    return ("ok" if all(c["ok"] for c in checks) else "problems"), checks


@dataclass(frozen=True)
class DueCheck:
    task_id: int
    title: str
    url: str
    completed_at: datetime
    assigned_to: int | None
    client_id: int | None
    attempts: int


async def due_checks(db, now: datetime) -> list[DueCheck]:
    since = now.astimezone(UTC).replace(tzinfo=None) - WINDOW  # completed_at es UTC sin zona
    client_id = Task.client_id.label("task_client")
    rows = (await db.execute(
        select(Task.id, Task.title, Task.link_url, Task.completed_at, Task.assigned_to, client_id,
               Project.client_id.label("project_client"), TaskPublishCheck.task_id.label("check_id"),
               TaskPublishCheck.task_completed_at, TaskPublishCheck.url.label("check_url"),
               TaskPublishCheck.status.label("check_status"), TaskPublishCheck.attempts)
        .outerjoin(Project, Project.id == Task.project_id)
        .outerjoin(TaskPublishCheck, TaskPublishCheck.task_id == Task.id)
        .where(
            Task.status == TaskStatus.completed,
            Task.completed_at.is_not(None),
            Task.link_url.is_not(None),
            Task.link_url != "",
            Task.retired_at.is_(None),
            or_(
                and_(Task.completed_at >= since, or_(
                    TaskPublishCheck.task_id.is_(None),
                    TaskPublishCheck.task_completed_at != Task.completed_at,
                    TaskPublishCheck.url != Task.link_url,
                )),
                and_(TaskPublishCheck.status == "pending", TaskPublishCheck.next_attempt_at <= now),
            ),
        )
        .order_by(Task.completed_at, Task.id)
        .limit(MAX_PER_CYCLE)
    )).all()
    out = []
    for row in rows:
        fresh = (row.check_id is None or row.task_completed_at != row.completed_at
                 or row.check_url != row.link_url)
        out.append(DueCheck(row.id, row.title, row.link_url.strip(), row.completed_at, row.assigned_to,
                            row.task_client or row.project_client, 0 if fresh else row.attempts))
    return out


def _skip(check: TaskPublishCheck, reason: str, now: datetime) -> None:
    check.status, check.error, check.checked_at, check.next_attempt_at = "skipped", reason, now, None
    check.http_status = check.final_url = check.results = None


async def _notify(db, due: DueCheck, check: TaskPublishCheck) -> None:
    if due.assigned_to is None:
        return
    key = f"{NOTIFICATION_TYPE}:task:{due.task_id}:{due.completed_at:%Y%m%dT%H%M%S}"
    exists = await db.scalar(select(Notification.id).where(
        Notification.user_id == due.assigned_to, Notification.dedupe_key == key,
    ))
    if exists is not None:
        return
    if check.status == "unreachable":
        message = f"No hemos podido abrir {due.url} ({cause_label(check.error) or 'sin respuesta'})."
    else:
        failed = [c["detail"] for c in (check.results or []) if not c.get("ok")]
        message = "Revisa: " + "; ".join(failed) + "."
    db.add(Notification(
        user_id=due.assigned_to, type=NOTIFICATION_TYPE,
        title=f"La página publicada tiene problemas: {due.title}"[:255],
        message=message[:2000], link_url=f"/tasks?task={due.task_id}",
        entity_type="task", entity_id=due.task_id, dedupe_key=key,
    ))


async def process(session_factory, due: DueCheck, now: datetime, *, fetcher=None) -> str:
    """Revisa una tarea y guarda el resultado. Devuelve el estado."""
    fetcher = fetcher or fetch
    async with session_factory() as db:
        hosts = await client_hosts(db, due.client_id) if due.client_id else set()
    reason = None
    try:
        check_url_syntax(due.url)
    except SSRFError:
        reason = "not_web"
    link_host = bare_host(due.url)
    if reason is None and due.client_id is None:
        reason = "no_client"
    if reason is None and (not link_host or not same_site(link_host, hosts)):
        reason = "other_site"

    result = None
    if reason is None:
        result = await fetcher(due.url, timeout=TIMEOUT_S, max_bytes=MAX_BYTES)

    async with session_factory() as db:
        check = await db.get(TaskPublishCheck, due.task_id)
        if check is None:
            check = TaskPublishCheck(task_id=due.task_id, attempts=0)
            db.add(check)
        check.url, check.task_completed_at = due.url, due.completed_at
        if reason is not None:
            _skip(check, reason, now)
            await db.commit()
            return check.status
        attempts = due.attempts + 1
        check.attempts, check.checked_at = attempts, now
        check.http_status, check.final_url = result.status_code, result.final_url
        check.error = result.error
        retryable = result.error is not None or result.status_code in _RETRYABLE_STATUS
        if retryable and attempts <= len(RETRY_DELAYS):
            check.status, check.next_attempt_at, check.results = "pending", now + RETRY_DELAYS[attempts - 1], None
            await db.commit()
            return check.status
        check.next_attempt_at = None
        if result.error is not None:
            check.status, check.results = "unreachable", None
        else:
            check.status, check.results = await asyncio.to_thread(evaluate, result)
        if check.status != "ok":
            await _notify(db, due, check)
        await db.commit()
        return check.status


@dataclass
class PublishCycleResult:
    due: int = 0
    failed: int = 0


async def run_cycle(session_factory, *, now: datetime | None = None, fetcher=None) -> PublishCycleResult:
    now = now or datetime.now(UTC)
    result = PublishCycleResult()
    async with session_factory() as db:
        items = await due_checks(db, now)
    result.due = len(items)
    for item in items:
        try:
            await process(session_factory, item, now, fetcher=fetcher)
        except Exception:  # noqa: BLE001 — una tarea no tumba a las demás
            result.failed += 1
            logger.exception("Revisión tras publicar: falló la tarea %s", item.task_id)
    return result
