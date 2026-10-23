"""Web del cliente caída, bloqueada o con cambios críticos sin revisar.

- ``client_site_down`` (crítica): alguna URL activa del cliente tiene una caída
  ``down`` abierta (2 ciclos fallidos seguidos, ver ``services/web/uptime.py``).
- ``client_site_blocked`` (aviso): un bloqueo (401/403/429/desafío) que dura
  más de ``UPTIME_BLOCKED_ALERT_MINUTES``: no podemos comprobar la web.
- ``client_web_critical_change`` (crítica): la vigilancia de cambios
  (``services/web/sweep.py``) detectó un cambio crítico (noindex, canonical
  borrado, página en error…) que nadie ha revisado. Se resuelve sola al
  revisarlo (``POST /api/web/changes/{id}/ack``). No cuentan las URLs
  archivadas ni las silenciadas ("no me avises").

Una incidencia por cliente (clave ``...:client:{id}:open``): se resuelve sola al
cerrarse la caída. La huella lleva los ids de las caídas (o de los cambios), así
que un descarte vale mientras dure ESA caída y una nueva vuelve a avisar.
Destinatarios: admins y responsables de proyectos activos/planificados del
cliente, siempre con lectura en el módulo ``web``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, exists, false, func, literal, or_, select

from backend.core.modules import is_enabled
from backend.db.models import (
    Client, Notification, Project, ProjectStatus, User, UserRole, WebChange, WebChangeItem, WebOutage,
    WebUptimeTarget, WebWatch,
)
from backend.services.incident_conditions import Condition, module_permission
from backend.services.web.digest import _RULE_LABEL, _path, changes_path
from backend.services.web.changes_views import changes_enabled
from backend.services.web.sweep import monitored_clients_clause
from backend.services.web.uptime import cause_label, local_when, monitored_clause

CLIENT_SITE_DOWN = "client_site_down"
CLIENT_SITE_BLOCKED = "client_site_blocked"
CLIENT_WEB_CRITICAL_CHANGE = "client_web_critical_change"
OUTAGE_CONDITIONS = (CLIENT_SITE_DOWN, CLIENT_SITE_BLOCKED)
WEB_CONDITIONS = (CLIENT_SITE_DOWN, CLIENT_SITE_BLOCKED, CLIENT_WEB_CRITICAL_CHANGE)
_MAX_LINES = 3
_KIND = {CLIENT_SITE_DOWN: "down", CLIENT_SITE_BLOCKED: "blocked"}
MODULE = "web"

_OWNED_PROJECT_STATUSES = (ProjectStatus.active, ProjectStatus.planning)


def _key(condition: str, client_id: int) -> str:
    return f"{condition}:client:{client_id}:open"


def _recipient_clause(user_id):
    """Admins, y quien lleva un proyecto operativo del cliente."""
    return or_(
        exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin),
        exists().where(
            Project.client_id == Client.id,
            Project.owner_id == user_id,
            Project.status.in_(_OWNED_PROJECT_STATUSES),
        ),
    )


def _open_outage(kind: str):
    return and_(
        WebOutage.target_id == WebUptimeTarget.id,
        WebUptimeTarget.client_id == Client.id,
        WebOutage.ended_at.is_(None),
        WebOutage.kind == kind,
        monitored_clause(),
    )


def pending_critical_clause():
    """Cambio crítico sin revisar de una URL que se sigue vigilando (correlado con ``Client``)."""
    return and_(
        WebChange.client_id == Client.id,
        WebChange.acknowledged_at.is_(None),
        WebChange.max_severity == "critical",
        WebWatch.id == WebChange.watch_id,
        WebWatch.archived_at.is_(None),
        WebWatch.muted.is_(False),
        monitored_clients_clause(),
        changes_enabled(Client.id),
    )


async def _collect_critical_changes(db, user_id: int) -> dict[str, Condition]:
    # Una sola consulta (la reconciliación tiene un presupuesto fijo de lecturas):
    # la regla crítica de cada cambio va en una subconsulta correlada.
    rule = (select(func.min(WebChangeItem.rule_code))
            .where(WebChangeItem.change_id == WebChange.id, WebChangeItem.severity == "critical")
            .scalar_subquery())
    rows = (await db.execute(
        select(Client.id, Client.name, WebChange.id.label("change_id"), WebChange.detected_at, WebWatch.url,
               rule.label("rule_code"))
        .select_from(WebChange)
        .join(WebWatch, WebWatch.id == WebChange.watch_id)
        .join(Client, Client.id == WebChange.client_id)
        .where(pending_critical_clause(), _recipient_clause(user_id), module_permission(user_id, MODULE))
        .order_by(Client.id, WebChange.detected_at.desc(), WebChange.id)
    )).all()
    if not rows:
        return {}
    labels = {r.change_id: _RULE_LABEL.get(r.rule_code, r.rule_code) for r in rows if r.rule_code}
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.id, []).append(row)
    result: dict[str, Condition] = {}
    for client_id, items in grouped.items():
        name = items[0].name or f"Cliente #{client_id}"
        lines = [f"{_path(item.url)}: {labels.get(item.change_id, 'cambio crítico')} "
                 f"(el {local_when(item.detected_at)})." for item in items[:_MAX_LINES]]
        if len(items) > _MAX_LINES:
            lines.append(f"Y {len(items) - _MAX_LINES} más.")
        count = len(items)
        title = (f"Cambio crítico en la web sin revisar: {name}" if count == 1
                 else f"{count} cambios críticos en la web sin revisar: {name}")
        key = _key(CLIENT_WEB_CRITICAL_CHANGE, client_id)
        ids = ",".join(sorted(str(item.change_id) for item in items))
        result[key] = Condition(
            key=key,
            kind=CLIENT_WEB_CRITICAL_CHANGE,
            entity_id=client_id,
            title=title[:255],
            message=" ".join(lines),
            fingerprint=hashlib.sha256(f"{key}:{ids}".encode()).hexdigest(),
            severity="critical",
            entity_type="client",
            entity_key=str(client_id),
            href=changes_path(client_id),
        )
    return result


async def collect_web_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    if not is_enabled(MODULE):
        return {}
    rows = (await db.execute(
        select(Client.id, Client.name, WebOutage.id.label("outage_id"), WebOutage.kind,
               WebOutage.started_at, WebOutage.cause, WebUptimeTarget.url, WebUptimeTarget.label)
        .select_from(WebOutage)
        .join(WebUptimeTarget, WebUptimeTarget.id == WebOutage.target_id)
        .join(Client, Client.id == WebUptimeTarget.client_id)
        .where(
            WebOutage.ended_at.is_(None), monitored_clause(),
            _recipient_clause(user_id), module_permission(user_id, MODULE),
        ).order_by(Client.id, WebOutage.started_at, WebOutage.id)
    )).all()
    grouped: dict[tuple[str, int], list] = {}
    for row in rows:
        condition = CLIENT_SITE_DOWN if row.kind == "down" else CLIENT_SITE_BLOCKED
        grouped.setdefault((condition, row.id), []).append(row)
    result: dict[str, Condition] = {}
    for (condition, client_id), items in grouped.items():
        name = items[0].name or f"Cliente #{client_id}"
        lines = []
        for item in items:
            where = item.label or item.url
            if condition == CLIENT_SITE_DOWN:
                cause = cause_label(item.cause)
                lines.append(f"{where} no responde desde el {local_when(item.started_at)}" + (f" ({cause})." if cause else "."))
            else:
                lines.append(f"{where} nos bloquea desde el {local_when(item.started_at)} "
                             f"({cause_label(item.cause) or 'bloqueo'}): no sabemos si está arriba.")
        title = (f"La web no responde: {name}" if condition == CLIENT_SITE_DOWN
                 else f"No podemos comprobar la web: {name}")
        key = _key(condition, client_id)
        outage_ids = ",".join(str(item.outage_id) for item in items)
        result[key] = Condition(
            key=key,
            kind=condition,
            entity_id=client_id,
            title=title[:255],
            message=" ".join(lines),
            fingerprint=hashlib.sha256(f"{key}:{outage_ids}".encode()).hexdigest(),
            severity="critical" if condition == CLIENT_SITE_DOWN else "warning",
            entity_type="client",
            entity_key=str(client_id),
            href=f"/clients/{client_id}?tab=web",
        )
    result.update(await _collect_critical_changes(db, user_id))
    return result


def web_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled(MODULE):
        return false()
    source = [Client.id == Notification.entity_id, _recipient_clause(user_id)]
    if current_only:
        source.append(or_(
            *(
                and_(
                    Notification.type == condition,
                    Notification.dedupe_key == func.concat(condition, ":client:", Client.id, ":open"),
                    select(literal(1)).select_from(WebOutage).where(_open_outage(_KIND[condition])).exists(),
                )
                for condition in OUTAGE_CONDITIONS
            ),
            and_(
                Notification.type == CLIENT_WEB_CRITICAL_CHANGE,
                Notification.dedupe_key == func.concat(CLIENT_WEB_CRITICAL_CHANGE, ":client:", Client.id, ":open"),
                select(literal(1)).select_from(WebChange).join(WebWatch, WebWatch.id == WebChange.watch_id)
                .where(pending_critical_clause()).exists(),
            ),
        ))
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "client",
        Notification.type.in_(WEB_CONDITIONS),
        module_permission(user_id, MODULE),
        select(literal(1)).where(*source).exists(),
    )
