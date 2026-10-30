"""Pipeline (CRM): historial de etapas, embudo, avisos y alta de leads.

- Las etapas abiertas van en orden (``STAGES``); ganado cierra el embudo y
  perdido sale de él desde cualquier etapa.
- ``record_status`` apunta la entrada en una etapa; lo llaman el alta y cada
  cambio de etapa. El embudo sólo lee esa tabla.
- Un lead nuevo avisa en la campana a los admins activos y a quien lo lleva,
  salvo a quien lo ha creado.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Lead, LeadStatus, LeadStatusHistory, User, UserRole
from backend.services.notification_service import create_notification
from backend.services.temporal import utc_now_naive

STAGES = (
    LeadStatus.new, LeadStatus.contacted, LeadStatus.discovery,
    LeadStatus.proposal, LeadStatus.negotiation, LeadStatus.won,
)
CLOSED = (LeadStatus.won, LeadStatus.lost)
STAGE_LABELS = {
    LeadStatus.new: "Nuevo", LeadStatus.contacted: "Contactado", LeadStatus.discovery: "Descubrimiento",
    LeadStatus.proposal: "Propuesta", LeadStatus.negotiation: "Negociación",
    LeadStatus.won: "Ganado", LeadStatus.lost: "Perdido",
}
_ORDER = {stage: index for index, stage in enumerate(STAGES)}


def record_status(db: AsyncSession, lead: Lead, status: LeadStatus, *, at: Optional[datetime] = None) -> None:
    db.add(LeadStatusHistory(lead_id=lead.id, status=status, entered_at=at or utc_now_naive()))


async def notify_new_lead(db: AsyncSession, lead: Lead, *, created_by: Optional[int], origin: str) -> None:
    """Campana de admins activos y de quien lo lleva (no de quien lo creó). No hace commit."""
    admin_ids = set(await db.scalars(select(User.id).where(User.is_active.is_(True), User.role == UserRole.admin)))
    recipients = admin_ids | ({lead.assigned_to} if lead.assigned_to else set())
    recipients.discard(created_by)
    who = lead.contact_name or lead.email
    message = f"{origin}." + (f" Contacto: {who}." if who else "")
    for user_id in sorted(recipients):
        await create_notification(
            db, user_id=user_id, type="lead_new", title=f"Lead nuevo: {lead.company_name}"[:255],
            message=message, link_url=f"/leads/{lead.id}", entity_type="lead", entity_id=lead.id,
        )


def visible_leads(user: User):
    """Quien no es admin sólo ve los suyos (la misma regla que el resto del Pipeline)."""
    return true() if user.role == UserRole.admin else Lead.assigned_to == user.id


async def funnel(db: AsyncSession, user: User, *, days: int, now: Optional[datetime] = None) -> dict:
    """Embudo de los leads creados en los últimos ``days`` días.

    Por etapa: cuántos llegaron (a ella o a una posterior), cuántos pasaron a la
    siguiente y la media de días que estuvieron en ella (sólo los que salieron).
    Tasa de cierre = ganados / (ganados + perdidos) de esos leads.
    """
    now = now or utc_now_naive()
    since = now - timedelta(days=days)
    leads = list(await db.scalars(select(Lead).where(Lead.created_at >= since, visible_leads(user))))
    if not leads:
        return {"days": days, "total": 0, "stages": [
            {"status": s.value, "label": STAGE_LABELS[s], "reached": 0, "moved_on": 0,
             "conversion_pct": None, "avg_days": None} for s in STAGES
        ], "won": 0, "lost": 0, "win_rate_pct": None}
    history: dict[int, list[LeadStatusHistory]] = {}
    for row in await db.scalars(select(LeadStatusHistory).where(
        LeadStatusHistory.lead_id.in_([lead.id for lead in leads]),
    ).order_by(LeadStatusHistory.lead_id, LeadStatusHistory.entered_at, LeadStatusHistory.id)):
        history.setdefault(row.lead_id, []).append(row)

    reached = {stage: 0 for stage in STAGES}
    moved_on = {stage: 0 for stage in STAGES}
    durations: dict[LeadStatus, list[float]] = {stage: [] for stage in STAGES}
    for lead in leads:
        rows = history.get(lead.id) or []
        furthest = max((_ORDER[row.status] for row in rows if row.status in _ORDER), default=_ORDER.get(lead.status, 0))
        for stage in STAGES[:furthest + 1]:
            reached[stage] += 1
        for stage in STAGES[:furthest]:
            moved_on[stage] += 1
        for current, following in zip(rows, rows[1:]):
            if current.status in _ORDER and current.status != LeadStatus.won:
                durations[current.status].append((following.entered_at - current.entered_at).total_seconds() / 86400)
    won = sum(1 for lead in leads if lead.status == LeadStatus.won)
    lost = sum(1 for lead in leads if lead.status == LeadStatus.lost)
    stages = []
    for stage in STAGES:
        spent = durations[stage]
        stages.append({
            "status": stage.value, "label": STAGE_LABELS[stage],
            "reached": reached[stage],
            "moved_on": moved_on[stage] if stage != LeadStatus.won else 0,
            "conversion_pct": (round(100 * moved_on[stage] / reached[stage], 1)
                               if reached[stage] and stage != LeadStatus.won else None),
            "avg_days": round(sum(spent) / len(spent), 1) if spent else None,
        })
    return {
        "days": days, "total": len(leads), "stages": stages, "won": won, "lost": lost,
        "win_rate_pct": round(100 * won / (won + lost), 1) if won + lost else None,
    }


async def followups_due(db: AsyncSession, user: User, day) -> list[Lead]:
    """Seguimientos de lead hasta ``day`` de quien mira (admins: también los sin asignar)."""
    mine = Lead.assigned_to == user.id
    if user.role == UserRole.admin:
        mine = or_(mine, Lead.assigned_to.is_(None))
    return list(await db.scalars(select(Lead).where(
        mine, Lead.next_followup_date.is_not(None), Lead.next_followup_date <= day,
        Lead.status.notin_(CLOSED),
    ).order_by(Lead.next_followup_date, Lead.company_name).limit(100)))
