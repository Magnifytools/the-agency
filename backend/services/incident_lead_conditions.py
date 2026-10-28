"""Seguimiento de lead vencido: aviso en la campana de quien lo lleva.

Un lead abierto (ni ganado ni perdido) con ``next_followup_date`` hasta hoy
abre ``lead_followup_due``. Lo recibe quien lo lleva; si no lo lleva nadie, los
admins. Clave por (lead, fecha): cambiar la fecha del seguimiento lo resuelve y,
si vuelve a vencer, avisa de nuevo. Necesita leer ``growth`` (el permiso del
Pipeline) y que el Pipeline no esté oculto.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, exists, false, func, or_, select

from backend.core.modules import is_enabled
from backend.db.models import Lead, LeadStatus, Notification, User, UserRole
from backend.services.incident_conditions import Condition, module_permission
from backend.services.temporal import business_today

LEAD_FOLLOWUP_DUE = "lead_followup_due"
LEAD_CONDITIONS = (LEAD_FOLLOWUP_DUE,)
_CLOSED = (LeadStatus.won, LeadStatus.lost)


def _recipient_clause(user_id: int):
    return or_(
        Lead.assigned_to == user_id,
        and_(Lead.assigned_to.is_(None), exists().where(
            User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin,
        )),
    )


async def collect_lead_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    if not is_enabled("leads"):
        return {}
    today = business_today(now=now)
    rows = (await db.execute(select(
        Lead.id, Lead.company_name, Lead.next_followup_date, Lead.next_followup_notes,
    ).where(
        Lead.next_followup_date.is_not(None), Lead.next_followup_date <= today,
        Lead.status.notin_(_CLOSED), _recipient_clause(user_id), module_permission(user_id, "growth"),
    ).order_by(Lead.id))).all()
    result: dict[str, Condition] = {}
    for row in rows:
        key = f"{LEAD_FOLLOWUP_DUE}:lead:{row.id}:{row.next_followup_date.isoformat()}"
        message = f"Tocaba el {row.next_followup_date:%d/%m/%Y}."
        if row.next_followup_notes:
            message += f" {row.next_followup_notes}"
        result[key] = Condition(
            key=key, kind=LEAD_FOLLOWUP_DUE, entity_id=row.id,
            title=f"Seguimiento pendiente: {row.company_name}"[:255],
            message=message[:1000],
            fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            entity_type="lead", entity_key=str(row.id), href=f"/leads/{row.id}",
        )
    return result


def lead_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled("leads"):
        return false()
    source = [Lead.id == Notification.entity_id, _recipient_clause(user_id)]
    if current_only:
        source += [
            Lead.status.notin_(_CLOSED),
            Notification.dedupe_key == func.concat(
                LEAD_FOLLOWUP_DUE, ":lead:", Lead.id, ":", func.to_char(Lead.next_followup_date, "YYYY-MM-DD"),
            ),
        ]
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "lead",
        Notification.type.in_(LEAD_CONDITIONS),
        module_permission(user_id, "growth"),
        exists().where(*source),
    )
