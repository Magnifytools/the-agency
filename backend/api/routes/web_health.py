"""Salud diaria de las webs y revisión tras publicar.

- ``GET /api/clients/{id}/web/health`` (lectura de ``web``): caducidad de
  certificado y dominio por host y, con la vigilancia de cambios encendida,
  robots.txt y sitemap por origen. Lo escribe el job ``web_health``.
- ``POST /api/clients/{id}/web/robots/review`` (escritura de ``web``): da por
  revisado el último cambio del robots.txt de un origen (resuelve la incidencia).
- ``GET/POST /api/tasks/{id}/publish-check`` (lectura/escritura de ``tasks``):
  la revisión de la página publicada de una tarea completada; el POST la vuelve a
  poner en cola (la hace el job ``publish_checks``, nunca la petición).
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import ClientWebSettings, Task, TaskPublishCheck, TaskStatus, User, WebHostExpiry, WebRobotsState
from backend.services.web.health import (
    CERT_CRITICAL_DAYS, CERT_WARNING_DAYS, DOMAIN_CRITICAL_DAYS, DOMAIN_WARNING_DAYS, days_left, level,
)
from backend.services.web.publish_check import SKIP_REASONS
from backend.services.web.uptime import cause_label
from backend.services.web.uptime_views import iso

router = APIRouter(tags=["web"])

MODULE = "web"


class RobotsReview(BaseModel):
    origin: str = Field(min_length=1, max_length=300)


def _expiry_view(row: WebHostExpiry, now: datetime) -> dict:
    cert_days = days_left(row.cert_expires_at, now) if row.cert_status != "no_https" else None
    domain_days = days_left(row.domain_expires_at, now) if row.domain_status in ("ok", "error") else None
    return {
        "host": row.host,
        "checked_at": iso(row.checked_at),
        "cert": {
            "status": row.cert_status,
            "expires_at": iso(row.cert_expires_at) if row.cert_status != "no_https" else None,
            "days_left": cert_days,
            "level": level(cert_days, CERT_WARNING_DAYS, CERT_CRITICAL_DAYS),
            "issuer": row.cert_issuer,
            "error": row.cert_error,
        },
        "domain": {
            "status": row.domain_status,
            "name": row.domain_name,
            "expires_at": iso(row.domain_expires_at) if row.domain_status in ("ok", "error") else None,
            "days_left": domain_days,
            "level": level(domain_days, DOMAIN_WARNING_DAYS, DOMAIN_CRITICAL_DAYS),
            "error": row.domain_error,
        },
    }


def _robots_view(row: WebRobotsState, reviewer: str | None) -> dict:
    return {
        "origin": row.origin,
        "checked_at": iso(row.checked_at),
        "status": row.robots_status,
        "error": row.robots_error,
        "body": row.robots_body,
        "blocks_all": row.robots_blocks_all,
        "previous_body": row.robots_previous_body,
        "changed_at": iso(row.robots_changed_at),
        "reviewed_at": iso(row.robots_reviewed_at),
        "reviewed_by": reviewer,
        "pending_review": row.robots_changed_at is not None and row.robots_reviewed_at is None,
        "sitemap": {
            "url": row.sitemap_url,
            "source": row.sitemap_source,
            "status": row.sitemap_status,
            "url_count": row.sitemap_url_count,
            "has_more": row.sitemap_has_more,
            "error": row.sitemap_error,
        },
    }


@router.get("/api/clients/{client_id}/web/health")
async def client_web_health(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    await get_client_or_404(client_id, db)
    now = datetime.now(UTC)
    hosts = (await db.scalars(select(WebHostExpiry).where(WebHostExpiry.client_id == client_id)
                              .order_by(WebHostExpiry.host))).all()
    web = await db.get(ClientWebSettings, client_id)
    changes_on = bool(web and web.changes_enabled)
    robots = []
    if changes_on:
        rows = (await db.execute(
            select(WebRobotsState, User.full_name)
            .outerjoin(User, User.id == WebRobotsState.robots_reviewed_by)
            .where(WebRobotsState.client_id == client_id)
            .order_by(WebRobotsState.origin)
        )).all()
        robots = [_robots_view(row, reviewer) for row, reviewer in rows]
    return {
        "expiry_enabled": settings.UPTIME_ENABLED,
        "robots_enabled": settings.WEB_SWEEP_ENABLED,
        "changes_enabled": changes_on,
        "thresholds": {
            "cert_warning_days": CERT_WARNING_DAYS, "cert_critical_days": CERT_CRITICAL_DAYS,
            "domain_warning_days": DOMAIN_WARNING_DAYS, "domain_critical_days": DOMAIN_CRITICAL_DAYS,
        },
        "hosts": [_expiry_view(row, now) for row in hosts],
        "robots": robots,
    }


@router.post("/api/clients/{client_id}/web/robots/review")
async def review_robots_change(
    client_id: int,
    body: RobotsReview,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    await get_client_or_404(client_id, db)
    row = await db.get(WebRobotsState, (client_id, body.origin))
    if row is None:
        raise HTTPException(status_code=404, detail="No hay robots.txt guardado para esa web")
    if row.robots_changed_at is not None and row.robots_reviewed_at is None:
        row.robots_reviewed_at, row.robots_reviewed_by = datetime.now(UTC), user.id
        await db.commit()
    return {"ok": True}


# ── Revisión tras publicar ───────────────────────────────────────────


def _current(task: Task, check: TaskPublishCheck | None) -> TaskPublishCheck | None:
    """La revisión sólo vale para la finalización y el enlace actuales de la tarea."""
    if check is None or task.status != TaskStatus.completed or task.completed_at is None:
        return None
    if check.task_completed_at != task.completed_at or check.url != (task.link_url or "").strip():
        return None
    return check


def _publish_view(task: Task, check: TaskPublishCheck | None) -> dict:
    eligible = task.status == TaskStatus.completed and bool((task.link_url or "").strip()) and task.completed_at
    base = {"enabled": settings.PUBLISH_CHECK_ENABLED, "url": (task.link_url or "").strip() or None}
    if check is None:
        if not eligible:
            return {**base, "status": "none"}
        return {**base, "status": "waiting" if settings.PUBLISH_CHECK_ENABLED else "disabled"}
    return {
        **base,
        "status": check.status,
        "checked_at": iso(check.checked_at),
        "attempts": check.attempts,
        "next_attempt_at": iso(check.next_attempt_at),
        "http_status": check.http_status,
        "final_url": check.final_url,
        "error": (SKIP_REASONS.get(check.error) if check.status == "skipped" else cause_label(check.error)),
        "results": check.results or [],
    }


async def _task_or_404(db: AsyncSession, task_id: int) -> Task:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/api/tasks/{task_id}/publish-check")
async def get_publish_check(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks")),
):
    task = await _task_or_404(db, task_id)
    return _publish_view(task, _current(task, await db.get(TaskPublishCheck, task_id)))


@router.post("/api/tasks/{task_id}/publish-check")
async def retry_publish_check(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    """Vuelve a poner en cola la revisión (p. ej. tras arreglar la página)."""
    task = await _task_or_404(db, task_id)
    link = (task.link_url or "").strip()
    if task.status != TaskStatus.completed or task.completed_at is None or not link:
        raise HTTPException(status_code=409, detail="Sólo se revisa el enlace de una tarea completada")
    if not settings.PUBLISH_CHECK_ENABLED:
        raise HTTPException(status_code=409, detail="La revisión tras publicar está apagada")
    check = await db.get(TaskPublishCheck, task_id)
    if check is None:
        check = TaskPublishCheck(task_id=task_id)
        db.add(check)
    check.url, check.task_completed_at = link, task.completed_at
    check.status, check.attempts, check.next_attempt_at = "pending", 0, datetime.now(UTC)
    check.checked_at = check.http_status = check.final_url = check.error = check.results = None
    await db.commit()
    return _publish_view(task, check)
