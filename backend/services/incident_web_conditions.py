"""Web del cliente caída o bloqueada, leída de las caídas abiertas del monitor.

- ``client_site_down`` (crítica): alguna URL activa del cliente tiene una caída
  ``down`` abierta (2 ciclos fallidos seguidos, ver ``services/web/uptime.py``).
- ``client_site_blocked`` (aviso): un bloqueo (401/403/429/desafío) que dura
  más de ``UPTIME_BLOCKED_ALERT_MINUTES``: no podemos comprobar la web.

Una incidencia por cliente (clave ``...:client:{id}:open``): se resuelve sola al
cerrarse la caída. La huella lleva los ids de las caídas, así que un descarte
vale mientras dure ESA caída y una caída nueva vuelve a avisar.
Destinatarios: admins y responsables de proyectos activos/planificados del
cliente, siempre con lectura en el módulo ``web``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, exists, false, func, literal, or_, select

from backend.core.modules import is_enabled
from backend.db.models import (
    Client, Notification, Project, ProjectStatus, User, UserRole, WebOutage, WebUptimeTarget,
)
from backend.services.incident_conditions import Condition, module_permission
from backend.services.web.uptime import cause_label, local_when, monitored_clause

CLIENT_SITE_DOWN = "client_site_down"
CLIENT_SITE_BLOCKED = "client_site_blocked"
WEB_CONDITIONS = (CLIENT_SITE_DOWN, CLIENT_SITE_BLOCKED)
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
    return result


def web_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled(MODULE):
        return false()
    source = [Client.id == Notification.entity_id, _recipient_clause(user_id)]
    if current_only:
        source.append(or_(*(
            and_(
                Notification.type == condition,
                Notification.dedupe_key == func.concat(condition, ":client:", Client.id, ":open"),
                select(literal(1)).select_from(WebOutage).where(_open_outage(_KIND[condition])).exists(),
            )
            for condition in WEB_CONDITIONS
        )))
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "client",
        Notification.type.in_(WEB_CONDITIONS),
        module_permission(user_id, MODULE),
        select(literal(1)).where(*source).exists(),
    )
