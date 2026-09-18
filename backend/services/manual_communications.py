"""Manual communication sources. Staging is atomic with the delivery intent."""
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.db.models import CommunicationRequest, Delivery, User, UserRole
from backend.services import deliveries

KINDS = frozenset({"pm_briefing", "daily_summary", "custom", "weekly_report", "connection_test"})


def authorize_request(source, actor, *, write=True):
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Usuario desactivado o no disponible")
    if source.kind not in KINDS or source.scope not in ("mine", "team"):
        raise HTTPException(404, "Fuente no encontrada")
    if actor.role != UserRole.admin:
        if source.owner_id != actor.id:
            raise HTTPException(403, "No tienes acceso a esta solicitud")
        if source.kind != "pm_briefing" or source.scope != "mine":
            raise HTTPException(403, "Este envío requiere rol administrador")
        if not any(p.module == "pm" and (p.can_write if write else p.can_read) for p in actor.permissions):
            raise HTTPException(403, "Sin permiso para este resumen PM")
    expected_destination = "owner_dm" if source.kind == "weekly_report" else "team_webhook"
    if source.destination_kind != expected_destination:
        raise HTTPException(409, "Destino incompatible con esta solicitud")


async def stage_request(db, actor, *, kind: str, scope: str, period_start: date,
                        period_end: date, title: str, content: str, intent_key: str | None = None):
    """No commit: request and intent either persist together or both roll back."""
    if not content.strip():
        raise HTTPException(400, "El mensaje está vacío")
    if len(content) > 50000:
        raise HTTPException(400, "El mensaje supera el límite de 50.000 caracteres")
    if period_end < period_start:
        raise HTTPException(422, "El período no es válido")
    destination_kind = "owner_dm" if kind == "weekly_report" else "team_webhook"
    values = dict(owner_id=actor.id, kind=kind, scope=scope, period_start=period_start,
                  period_end=period_end, title=title, content=content.strip(), destination_kind=destination_kind)
    candidate = SimpleNamespace(**values)
    authorize_request(candidate, actor)
    # Serialize new snapshots for the same actor before locking sources/intents.
    # Different content must not bypass an uncertain earlier request for this scope.
    await db.execute(select(User.id).where(User.id == actor.id).with_for_update())
    if intent_key:
        # A replay remains the same intention across midnight/config changes.
        key = deliveries.fingerprint(["explicit-manual", actor.id, kind, intent_key])
        existing = await db.scalar(select(CommunicationRequest).where(CommunicationRequest.request_key == key))
        if existing:
            authorize_request(existing, actor)
            immutable_fields = ("owner_id", "kind", "scope", "title", "content", "destination_kind")
            if any(getattr(existing, field) != values[field] for field in immutable_fields):
                raise HTTPException(409, "La clave de solicitud ya corresponde a otro contenido o ámbito")
            if kind != "connection_test" and (existing.period_start != period_start or existing.period_end != period_end):
                raise HTTPException(409, "La clave de solicitud ya corresponde a otro período")
            previous = await db.scalar(select(Delivery).where(Delivery.source_kind == "communication", Delivery.source_id == existing.id)
                                       .order_by(Delivery.created_at.desc(), Delivery.id).limit(1))
            if previous:
                return previous
    _, _, destination = await deliveries.destination_config(db, "communication", candidate)
    key = deliveries.fingerprint(["explicit-manual", actor.id, kind, intent_key]) if intent_key else deliveries.fingerprint([values, destination])
    prior = (await db.execute(select(Delivery).join(CommunicationRequest,
        (Delivery.source_kind == "communication") & (Delivery.source_id == CommunicationRequest.id)
    ).where(CommunicationRequest.owner_id == actor.id, CommunicationRequest.kind == kind,
            CommunicationRequest.scope == scope, CommunicationRequest.period_start == period_start,
            CommunicationRequest.period_end == period_end, CommunicationRequest.request_key != key,
            Delivery.status.in_(["pending", "sending", "uncertain"])
    ).with_for_update(of=Delivery).execution_options(populate_existing=True))).scalars().all()
    for row in prior:
        if row.status == "pending":
            row.status, row.message = "cancelled", "Sustituido por un nuevo texto revisado"
        elif row.status == "sending":
            raise HTTPException(409, "Hay un envío en curso. Revisa su recibo antes de enviar otra versión")
        elif not await db.scalar(select(Delivery.id).where(Delivery.resend_of == row.id).limit(1)):
            raise HTTPException(409, "Hay un envío incierto. Revisa su recibo antes de enviar otra versión")
    await db.execute(insert(CommunicationRequest).values(request_key=key, **values).on_conflict_do_nothing(index_elements=["request_key"]))
    source = await db.scalar(select(CommunicationRequest).where(CommunicationRequest.request_key == key)
                             .with_for_update().execution_options(populate_existing=True))
    return await deliveries.stage_delivery(db, "communication", source.id, actor)


async def enqueue_request(db, actor, **kwargs):
    row = await stage_request(db, actor, **kwargs)
    await db.commit()
    source = await db.get(CommunicationRequest, row.source_id)
    receipt = await deliveries.receipt(db, row, source)
    if receipt["status"] == "sent":
        receipt["message"] = "Este envío ya estaba confirmado. Se muestra su recibo, sin enviar de nuevo."
    return receipt


def format_briefing(briefing):
    lines = [f"# {briefing['greeting']}", f"**Briefing del {briefing['date']}**"]
    if briefing.get("suggestion"):
        lines.append(f"> *{briefing['suggestion']}*")
    for key, heading in (("priorities", "Tareas planificadas para hoy"), ("alerts", "Tareas vencidas"), ("followups", "Seguimientos pendientes")):
        if briefing.get(key):
            lines.append(f"\n**{heading}:**")
            for item in briefing[key]:
                prefix = f"[{item['client']}] " if item.get("client") else ""
                suffix = f" ({item['days_overdue']} días)" if key == "alerts" else ""
                lines.append(f"- {prefix}{item.get('title', item.get('subject', ''))}{suffix}")
    if not any(briefing.get(key) for key in ("priorities", "alerts", "followups")):
        lines.append("\n*No hay tareas planificadas, vencidas ni seguimientos pendientes para hoy.*")
    return "\n".join(lines)
