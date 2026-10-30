"""Lecturas de la vigilancia de cambios: lo que pintan el API, la ficha y el
estado del cliente. Nada de esto escribe."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, exists, func, select

from backend.db.models import ClientWebSettings, WebChange, WebChangeItem, WebWatch, WebWatchState
from backend.services.web.digest import _RULE_LABEL
from backend.services.web.uptime_views import iso

SEVERITIES = ("critical", "warning", "info")
SEVERITY_ORDER = case(
    (WebChangeItem.severity == "critical", 0), (WebChangeItem.severity == "warning", 1), else_=2,
)


def watch_view(watch: WebWatch, state: WebWatchState | None, *, checking: bool = False) -> dict:
    return {
        "id": str(watch.id),
        "client_id": watch.client_id,
        "url": watch.url,
        "label": watch.label,
        "is_active": watch.is_active,
        "archived_at": iso(watch.archived_at),
        "watch_seo": watch.watch_seo,
        "watch_content": watch.watch_content,
        "watch_links": watch.watch_links,
        "watch_html": watch.watch_html,
        "content_selector": watch.content_selector,
        "ignore_selectors": watch.ignore_selectors,
        "ignore_regexes": watch.ignore_regexes,
        "muted": watch.muted,
        "source": watch.source,
        "check_requested_at": iso(watch.check_requested_at),
        "created_at": iso(watch.created_at),
        "updated_at": iso(watch.updated_at),
        "checking": checking,
        "state": None if state is None else {
            "last_checked_at": iso(state.last_checked_at),
            "last_changed_at": iso(state.last_changed_at),
            "last_status_code": state.last_status_code,
            "last_final_url": state.last_final_url,
            "last_error": state.last_error,
            "consecutive_errors": state.consecutive_errors,
            "needs_js_render": state.needs_js_render,
            # Hay sección acotada y hoy no casa: se vigila la página entera.
            "scope_missed": state.scope_missed,
            "title": (state.seo_json or {}).get("title"),
            "word_count": (state.seo_json or {}).get("word_count"),
        },
    }


def item_view(item: WebChangeItem) -> dict:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "field": item.field,
        "severity": item.severity,
        "rule_code": item.rule_code,
        "rule_label": _RULE_LABEL.get(item.rule_code, item.rule_code),
        "before_val": item.before_val,
        "after_val": item.after_val,
        "detail": item.detail,
    }


def change_view(change: WebChange, *, url: str | None = None, label: str | None = None,
                client_name: str | None = None, items: list[WebChangeItem] | None = None) -> dict:
    return {
        "id": str(change.id),
        "client_id": change.client_id,
        "client_name": client_name,
        "watch_id": str(change.watch_id),
        "url": url,
        "label": label,
        "run_id": str(change.run_id) if change.run_id else None,
        "max_severity": change.max_severity,
        "detected_at": iso(change.detected_at),
        "acknowledged_at": iso(change.acknowledged_at),
        "acknowledged_by": change.acknowledged_by,
        "acknowledged_by_label": change.acknowledged_by_label,
        "note": change.note,
        "has_diff": bool(change.snapshot_id or change.prev_snapshot_id),
        "items": [item_view(i) for i in (items or [])],
    }


async def items_by_change(db, change_ids: list) -> dict:
    """Los items de muchos cambios en UNA consulta (no N+1), críticos primero."""
    if not change_ids:
        return {}
    out: dict = {}
    for item in (await db.scalars(
        select(WebChangeItem).where(WebChangeItem.change_id.in_(change_ids))
        .order_by(WebChangeItem.change_id, SEVERITY_ORDER, WebChangeItem.created_at, WebChangeItem.id)
    )).all():
        out.setdefault(item.change_id, []).append(item)
    return out


def changes_enabled(client_id_column):
    """El cliente tiene la vigilancia de cambios encendida (correlado con su id)."""
    return exists().where(ClientWebSettings.client_id == client_id_column,
                          ClientWebSettings.changes_enabled.is_(True))


async def client_blocks(db, client_ids: list[int]) -> dict[int, dict]:
    """Resumen por cliente para su estado: sólo clientes con la vigilancia
    encendida y URLs propias (no archivadas). Los cambios sin revisar cuentan si la URL no está
    silenciada: silenciar es "no me avises", y el estado avisa."""
    if not client_ids:
        return {}
    watches = (await db.execute(
        select(
            WebWatch.client_id,
            func.count().filter(WebWatch.is_active.is_(True)),
            func.count(WebWatchState.last_error).filter(WebWatch.is_active.is_(True)),
            func.max(WebWatchState.last_checked_at),
        ).outerjoin(WebWatchState, WebWatchState.watch_id == WebWatch.id)
        .where(WebWatch.client_id.in_(client_ids), WebWatch.archived_at.is_(None),
               changes_enabled(WebWatch.client_id))
        .group_by(WebWatch.client_id)
    )).all()
    out: dict[int, dict] = {
        client_id: {"watches_active": active, "watches_with_error": errors, "last_checked_at": iso(last),
                    "critical": 0, "warning": 0, "info": 0}
        for client_id, active, errors, last in watches
    }
    if not out:
        return out
    for client_id, severity, count in (await db.execute(
        select(WebChange.client_id, WebChange.max_severity, func.count())
        .join(WebWatch, WebWatch.id == WebChange.watch_id)
        .where(WebChange.client_id.in_(list(out)), WebChange.acknowledged_at.is_(None),
               WebWatch.archived_at.is_(None), WebWatch.muted.is_(False))
        .group_by(WebChange.client_id, WebChange.max_severity)
    )).all():
        if severity in SEVERITIES:
            out[client_id][severity] = count
    return out


def status_reason(block: dict) -> tuple[str, str] | None:
    """Un cambio crítico sin revisar pide mirar (Vigilar), como hacía Vigil."""
    critical = block.get("critical") or 0
    if critical:
        plural = "s" if critical > 1 else ""
        return "watch", f"{critical} cambio{plural} crítico{plural} en la web sin revisar"
    return None


def is_stale_mark(mark: datetime | None, cutoff: datetime) -> bool:
    return mark is None or mark < cutoff
