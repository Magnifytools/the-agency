"""Read-only, JSON-safe projection of pending incident decisions for commands."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased, noload

from backend.db.models import Notification, User, UserRole
from backend.services.incidents import incident_response, visible_incident_clause
from backend.services.temporal import utc_isoformat


def _serialize_item(row: Notification, recipient_name: str | None) -> dict:
    incident = incident_response(row)
    return {
        "type": "incident",
        "id": incident.id,
        "revision": incident.revision,
        "condition_type": incident.condition_type,
        "state": incident.state,
        "severity": incident.severity,
        "title": incident.title,
        "label": incident.title,
        "message": incident.message,
        "href": incident.href,
        "entity_type": incident.entity_type,
        "entity_key": incident.entity_key,
        "created_at": utc_isoformat(incident.created_at),
        "snoozed_until": utc_isoformat(incident.snoozed_until),
        "recipient_id": row.user_id,
        "recipient_name": recipient_name,
    }


async def query_decisions(
    db,
    actor: User,
    scope: str = "mine",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Return currently active decisions without reconciling or mutating them.

    Snoozed incidents are deliberately absent: they remain deferred until the
    reconciliation worker reactivates them. Team scope is an administrative
    operation, while every returned row must still pass the recipient's live
    source and permission checks.
    """
    if scope not in {"mine", "team"}:
        raise HTTPException(422, "El ámbito debe ser mine o team")
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(422, "La página debe ser positiva y el tamaño estar entre 1 y 100")
    if scope == "team" and (not actor.is_active or actor.role != UserRole.admin):
        raise HTTPException(403, "Sólo un administrador activo puede consultar decisiones del equipo")

    recipient = aliased(User)
    conditions = [
        Notification.incident_state == "active",
        visible_incident_clause(Notification.user_id, current_only=True),
    ]
    if scope == "mine":
        conditions.append(Notification.user_id == actor.id)

    total = await db.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
    rows = (await db.execute(
        select(Notification, recipient.full_name)
        .options(noload(Notification.user))
        .join(recipient, recipient.id == Notification.user_id)
        .where(*conditions)
        .order_by(Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()
    items = [_serialize_item(row, recipient_name) for row, recipient_name in rows]
    return {
        "kind": "decisions",
        "scope": scope,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
        "items": items,
    }
