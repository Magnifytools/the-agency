"""Webs: cambios detectados y barridos (portado de ``Vigil/backend/app/api/changes.py``).

Permisos (módulo ``web``): leer = ver la lista, el detalle y los diffs;
escribir = marcar como revisado. Revisar un cambio crítico resuelve su
incidencia (``client_web_critical_change``) en la siguiente pasada.
"""
from __future__ import annotations

import asyncio
import gzip
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.db.database import get_db
from backend.db.models import Client, User, WebChange, WebChangeItem, WebRunError, WebSnapshot, WebSweepRun, WebWatch
from backend.schemas.web import ChangeAck, ChangeAckAll, Severity
from backend.services.web.changes_views import SEVERITIES, change_view, items_by_change
from backend.services.web.html_diff import diff_html
from backend.services.web.uptime_views import iso

router = APIRouter(tags=["web"])

MODULE = "web"


def _uuid(value: str, what: str = "Cambio") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} no encontrado")


async def _change_or_404(db: AsyncSession, change_id: str) -> WebChange:
    change = await db.get(WebChange, _uuid(change_id))
    if change is None:
        raise HTTPException(status_code=404, detail="Cambio no encontrado")
    return change


def _filters(*, client_id: int | None, kind: str | None, since: date | None, watch_id: uuid.UUID | None):
    """Filtros que acotan la lista Y los contadores. Severidad y revisado NO van
    aquí: los contadores los ignoran (lección 0decies de Vigil)."""
    clauses = []
    if client_id is not None:
        clauses.append(WebChange.client_id == client_id)
    if watch_id is not None:
        clauses.append(WebChange.watch_id == watch_id)
    if since is not None:
        clauses.append(WebChange.detected_at >= datetime.combine(since, datetime.min.time(), tzinfo=UTC))
    if kind:
        clauses.append(exists().where(WebChangeItem.change_id == WebChange.id, WebChangeItem.kind == kind))
    return clauses


@router.get("/api/web/changes")
async def list_changes(
    client_id: int | None = None,
    watch_id: str | None = None,
    severity: Severity | None = None,
    kind: str | None = Query(None, pattern="^(seo|content|links|html|availability)$"),
    acknowledged: bool | None = None,
    since: date | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Cambios de todos los clientes (o de uno), lo más reciente primero.

    ``counts`` (todos) y ``counts_pending`` (sin revisar) por severidad se
    calculan IGNORANDO los filtros de severidad y de revisado: así "Críticos 1 ·
    Avisos 3 · Menores 7" no cambia al pulsar uno (si contara lo ya filtrado, los
    otros dirían 0 y dejarían de servir para decidir a dónde ir). ``truncated``
    dice si el ``limit`` ha dejado cosas fuera, medido contra lo que se pide.
    """
    if client_id is not None:
        await get_client_or_404(client_id, db)
    watch_uuid = _uuid(watch_id, "URL") if watch_id else None
    base = _filters(client_id=client_id, kind=kind, since=since, watch_id=watch_uuid)

    query = (select(WebChange, WebWatch.url, WebWatch.label, Client.name)
             .join(WebWatch, WebWatch.id == WebChange.watch_id)
             .join(Client, Client.id == WebChange.client_id)
             .where(*base))
    if severity:
        query = query.where(WebChange.max_severity == severity)
    if acknowledged is True:
        query = query.where(WebChange.acknowledged_at.is_not(None))
    elif acknowledged is False:
        query = query.where(WebChange.acknowledged_at.is_(None))
    rows = (await db.execute(query.order_by(WebChange.detected_at.desc(), WebChange.id).limit(limit))).all()

    counts = dict.fromkeys(SEVERITIES, 0)
    pending = dict.fromkeys(SEVERITIES, 0)
    for sev, is_pending, n in (await db.execute(
        select(WebChange.max_severity, WebChange.acknowledged_at.is_(None), func.count())
        .where(*base).group_by(WebChange.max_severity, WebChange.acknowledged_at.is_(None))
    )).all():
        if sev in counts:
            counts[sev] += n
            if is_pending:
                pending[sev] += n
    for bucket in (counts, pending):
        bucket["all"] = sum(bucket[s] for s in SEVERITIES)

    if acknowledged is False:
        expected_by = pending
    elif acknowledged is True:
        expected_by = {k: counts[k] - pending[k] for k in counts}
    else:
        expected_by = counts
    expected = expected_by[severity] if severity else expected_by["all"]

    items = await items_by_change(db, [r[0].id for r in rows])
    return {
        "changes": [change_view(c, url=url, label=label, client_name=name, items=items.get(c.id))
                    for c, url, label, name in rows],
        "counts": counts,
        "counts_pending": pending,
        "total": expected,
        "truncated": len(rows) >= limit and expected > len(rows),
    }


@router.get("/api/web/changes/{change_id}")
async def get_change(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    change = await _change_or_404(db, change_id)
    watch = await db.get(WebWatch, change.watch_id)
    client_name = await db.scalar(select(Client.name).where(Client.id == change.client_id))
    items = (await items_by_change(db, [change.id])).get(change.id, [])
    return {
        "change": change_view(change, url=watch.url, label=watch.label, client_name=client_name, items=items),
        "watch": {"id": str(watch.id), "url": watch.url, "label": watch.label, "client_id": watch.client_id,
                  "archived_at": iso(watch.archived_at), "watch_html": watch.watch_html},
    }


async def _snapshot_column(db: AsyncSession, snapshot_id, column) -> tuple[bool, bytes | str | None]:
    """(existe la captura, valor de la columna)."""
    if snapshot_id is None:
        return False, None
    row = (await db.execute(select(column).where(WebSnapshot.id == snapshot_id))).one_or_none()
    return (row is not None), (row[0] if row is not None else None)


async def _text(db: AsyncSession, snapshot_id) -> str | None:
    if snapshot_id is None:
        return None
    row = (await db.execute(select(WebSnapshot.text_inline, WebSnapshot.text_gz)
                            .where(WebSnapshot.id == snapshot_id))).one_or_none()
    if row is None:
        return None
    if row.text_inline:
        return row.text_inline
    return await asyncio.to_thread(lambda: gzip.decompress(row.text_gz).decode()) if row.text_gz else None


@router.get("/api/web/changes/{change_id}/diff")
async def get_diff(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Texto vigilado de antes y de después, para pintar el diff en la ficha."""
    change = await _change_or_404(db, change_id)
    return {"before": await _text(db, change.prev_snapshot_id), "after": await _text(db, change.snapshot_id)}


@router.get("/api/web/changes/{change_id}/html-diff")
async def get_html_diff(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Trozos del HTML NORMALIZADO que cambiaron (el mismo sobre el que se calcula
    el hash, no el crudo: el crudo enseñaría diferencias que no dispararon el
    aviso). ``available: false`` SIEMPRE trae un ``reason`` (lección 0septies de
    Vigil): ``sin_actual``, ``sin_anterior`` o ``demasiado_grande``."""
    change = await _change_or_404(db, change_id)
    _, after_gz = await _snapshot_column(db, change.snapshot_id, WebSnapshot.html_gz)
    if after_gz is None:
        # El HTML sólo se guarda con "Vigilar HTML" activo: se encendió después.
        return {"available": False, "reason": "sin_actual"}
    _, before_gz = await _snapshot_column(db, change.prev_snapshot_id, WebSnapshot.html_gz)
    if before_gz is None:
        # Primera captura con HTML guardado: no hay contra qué comparar.
        return {"available": False, "reason": "sin_anterior"}

    def compute() -> dict:
        return diff_html(gzip.decompress(before_gz).decode(), gzip.decompress(after_gz).decode())

    result = await asyncio.to_thread(compute)
    if result["too_big"]:
        return {"available": False, "reason": "demasiado_grande", "stats": result["stats"]}
    return {"available": True, **result}


@router.post("/api/web/changes/{change_id}/ack")
async def ack_change(
    change_id: str,
    body: ChangeAck,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    change = await _change_or_404(db, change_id)
    change.acknowledged_by = user.id
    change.acknowledged_by_label = (user.full_name or user.email or "")[:120] or None
    change.acknowledged_at = datetime.now(UTC)
    change.note = body.note
    await db.commit()
    items = (await items_by_change(db, [change.id])).get(change.id, [])
    return change_view(change, items=items)


@router.post("/api/web/changes/ack-all")
async def ack_all(
    body: ChangeAckAll,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Marca como revisado lo PENDIENTE que se está viendo. Sólo toca filas sin
    revisar: reescribir quién y cuándo revisó otra cosa borraría el único rastro
    de que alguien la miró."""
    if body.client_id is not None:
        await get_client_or_404(body.client_id, db)
    query = update(WebChange).where(WebChange.acknowledged_at.is_(None))
    if body.client_id is not None:
        query = query.where(WebChange.client_id == body.client_id)
    if body.severity:
        query = query.where(WebChange.max_severity == body.severity)
    result = await db.execute(query.values(
        acknowledged_by=user.id, acknowledged_by_label=(user.full_name or user.email or "")[:120] or None,
        acknowledged_at=datetime.now(UTC),
    ))
    await db.commit()
    return {"acknowledged": result.rowcount or 0}


# ── Barridos ─────────────────────────────────────────────────────────


def _run_view(run: WebSweepRun) -> dict:
    return {
        "id": str(run.id), "client_id": run.client_id, "run_date": run.run_date.isoformat(),
        "trigger": run.trigger, "status": run.status, "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at), "watches_total": run.watches_total,
        "watches_done": run.watches_done, "watches_error": run.watches_error,
        "changes_found": run.changes_found, "notified_at": iso(run.notified_at),
        "notify_status": run.notify_status, "notify_error": run.notify_error,
    }


@router.get("/api/clients/{client_id}/web/runs")
async def list_runs(
    client_id: int,
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    await get_client_or_404(client_id, db)
    runs = (await db.scalars(select(WebSweepRun).where(WebSweepRun.client_id == client_id)
                             .order_by(WebSweepRun.started_at.desc()).limit(limit))).all()
    return {"runs": [_run_view(r) for r in runs]}


@router.get("/api/web/runs/{run_id}/errors")
async def run_errors(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    run = await db.get(WebSweepRun, _uuid(run_id, "Barrido"))
    if run is None:
        raise HTTPException(status_code=404, detail="Barrido no encontrado")
    rows = (await db.execute(
        select(WebRunError, WebWatch.url).outerjoin(WebWatch, WebWatch.id == WebRunError.watch_id)
        .where(WebRunError.run_id == run.id).order_by(WebRunError.created_at, WebRunError.id)
    )).all()
    return {"run": _run_view(run), "errors": [{
        "id": str(e.id), "watch_id": str(e.watch_id) if e.watch_id else None, "url": url, "kind": e.kind,
        "message": e.message, "status_code": e.status_code, "created_at": iso(e.created_at),
    } for e, url in rows]}


