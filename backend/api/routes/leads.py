"""CRM Leads — Pipeline de ventas."""
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Optional

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select, func as sa_func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import (
    Lead, LeadActivity, LeadStatus, LeadSource, LeadActivityType,
    Client, ClientStatus, ContractType, User, UserRole,
)
from backend.api.deps import get_current_user, require_module
from backend.api.utils.db_helpers import safe_refresh
from backend.schemas.lead import (
    LeadCreate, LeadUpdate, LeadResponse, LeadDetailResponse,
    LeadActivityCreate, LeadActivityResponse,
    PipelineSummary, PipelineStageSummary,
    LeadReminderResponse, LeadFunnel, LeadInbound,
)
from backend.config import settings
from backend.core.rate_limiter import public_link_limiter
from backend.services import lead_pipeline

router = APIRouter(prefix="/api/leads", tags=["leads"])

_STATUS_LABELS: dict[str, str] = {
    "new": "Nuevo",
    "contacted": "Contactado",
    "qualified": "Cualificado",
    "discovery": "Descubrimiento",
    "proposal": "Propuesta",
    "negotiation": "Negociación",
    "won": "Ganado",
    "lost": "Perdido",
    "on_hold": "En espera",
}

def _status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


def _lead_to_response(lead: Lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        email=lead.email,
        phone=lead.phone,
        website=lead.website,
        linkedin_url=lead.linkedin_url,
        status=lead.status,
        source=lead.source,
        assigned_to=lead.assigned_to,
        assigned_user_name=lead.assigned_user.full_name if lead.assigned_user else None,
        estimated_value=lead.estimated_value,
        service_interest=lead.service_interest,
        currency=lead.currency,
        notes=lead.notes,
        industry=lead.industry,
        company_size=lead.company_size,
        current_website_traffic=lead.current_website_traffic,
        next_followup_date=lead.next_followup_date,
        next_followup_notes=lead.next_followup_notes,
        last_contacted_at=lead.last_contacted_at,
        converted_client_id=lead.converted_client_id,
        converted_at=lead.converted_at,
        lost_reason=lead.lost_reason,
        estimated_close_date=lead.estimated_close_date,
        probability=lead.probability,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def _activity_to_response(act: LeadActivity) -> LeadActivityResponse:
    return LeadActivityResponse(
        id=act.id,
        lead_id=act.lead_id,
        user_id=act.user_id,
        user_name=act.user.full_name if act.user else None,
        activity_type=act.activity_type,
        title=act.title,
        description=act.description,
        created_at=act.created_at,
    )


# --- Pipeline Summary ---

@router.get("/pipeline-summary", response_model=PipelineSummary)
async def pipeline_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    query = select(
        Lead.status,
        sa_func.count(Lead.id).label("count"),
        sa_func.coalesce(sa_func.sum(Lead.estimated_value), 0).label("total_value"),
    )
    # Workers only see their leads
    if current_user.role != UserRole.admin:
        query = query.where(Lead.assigned_to == current_user.id)
    query = query.group_by(Lead.status)
    result = await db.execute(query)
    rows = result.all()

    stages = []
    total_leads = 0
    total_value = Decimal("0")
    for row in rows:
        stages.append(PipelineStageSummary(
            status=row.status,
            count=row.count,
            total_value=Decimal(str(row.total_value)),
        ))
        total_leads += row.count
        total_value += Decimal(str(row.total_value))

    # Weighted pipeline value: sum(estimated_value * probability / 100) for active leads
    wq = select(
        sa_func.coalesce(
            sa_func.sum(Lead.estimated_value * Lead.probability / 100), 0
        ).label("weighted")
    ).where(
        Lead.probability.isnot(None), Lead.estimated_value.isnot(None),
        # Sólo lo que aún está en juego: ganados y perdidos ya no son "probables".
        Lead.status.notin_(lead_pipeline.CLOSED),
    )
    if current_user.role != UserRole.admin:
        wq = wq.where(Lead.assigned_to == current_user.id)
    wr = await db.execute(wq)
    weighted_value = Decimal(str(wr.scalar() or 0))

    return PipelineSummary(
        stages=stages,
        total_leads=total_leads,
        total_value=total_value,
        weighted_value=weighted_value,
    )


# --- Reminders ---

@router.get("/reminders", response_model=list[LeadReminderResponse])
async def lead_reminders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    today = date.today()
    threshold = today + timedelta(days=3)

    query = select(Lead).options(selectinload(Lead.assigned_user)).where(
        Lead.next_followup_date <= threshold,
        Lead.status.notin_([LeadStatus.won, LeadStatus.lost]),
    )
    if current_user.role != UserRole.admin:
        query = query.where(Lead.assigned_to == current_user.id)
    query = query.order_by(Lead.next_followup_date.asc())

    result = await db.execute(query)
    leads = result.scalars().all()

    reminders = []
    for lead in leads:
        days = (lead.next_followup_date - today).days if lead.next_followup_date else 0
        reminders.append(LeadReminderResponse(
            id=lead.id,
            company_name=lead.company_name,
            contact_name=lead.contact_name,
            next_followup_date=lead.next_followup_date,
            next_followup_notes=lead.next_followup_notes,
            status=lead.status,
            assigned_user_name=lead.assigned_user.full_name if lead.assigned_user else None,
            days_until_followup=days,
        ))
    return reminders


# --- Formulario web ---

@router.post("/inbound", status_code=status.HTTP_201_CREATED)
async def inbound_lead(
    data: LeadInbound,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_lead_token: Optional[str] = Header(None),
):
    """Entrada pública para el formulario de la web: crea un lead "Nuevo" con
    origen web, sin asignar, y avisa a los admins. Sin ``LEADS_WEBHOOK_TOKEN``
    configurado, o con un token distinto, el mismo 404. 20/min por IP."""
    client_ip = request.client.host if request.client else "unknown"
    public_link_limiter.check(f"lead-inbound:{client_ip}", max_requests=20, window_seconds=60)
    expected = settings.LEADS_WEBHOOK_TOKEN
    if not expected or not x_lead_token or not secrets.compare_digest(x_lead_token, expected):
        raise HTTPException(status_code=404, detail="Not Found")
    name = next((v.strip() for v in (data.company, data.name, data.email) if v and v.strip()), None)
    if name is None:
        raise HTTPException(status_code=422, detail="Hace falta empresa, nombre o email")
    notes = "\n\n".join(filter(None, [
        (data.message or "").strip() or None,
        f"Desde: {data.page_url.strip()}" if data.page_url and data.page_url.strip() else None,
    ])) or None
    lead = Lead(
        company_name=name[:200],
        contact_name=(data.name or "").strip() or None,
        email=(data.email or "").strip() or None,
        phone=(data.phone or "").strip() or None,
        website=(data.website or "").strip() or None,
        notes=notes, status=LeadStatus.new, source=LeadSource.website,
    )
    db.add(lead)
    await db.flush()
    lead_pipeline.record_status(db, lead, LeadStatus.new)
    await lead_pipeline.notify_new_lead(db, lead, created_by=None, origin="Ha llegado por el formulario de la web")
    await db.commit()
    return {"id": lead.id}


# --- Embudo y seguimientos ---

@router.get("/funnel", response_model=LeadFunnel)
async def lead_funnel(
    days: int = Query(180, ge=7, le=730),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    """Conversión entre etapas, días en cada una y tasa de cierre de los leads
    creados en los últimos ``days`` días (quien no es admin, sólo los suyos)."""
    return await lead_pipeline.funnel(db, current_user, days=days)


@router.get("/agenda", response_model=list[LeadReminderResponse])
async def lead_agenda(
    date_: date = Query(..., alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    """Seguimientos de lead de Mi agenda: los míos (y, si soy admin, los sin
    asignar) con fecha hasta ese día, de leads abiertos."""
    leads = await lead_pipeline.followups_due(db, current_user, date_)
    assignees = {lead.assigned_to for lead in leads if lead.assigned_to}
    names = dict((await db.execute(
        select(User.id, User.full_name).where(User.id.in_(assignees))
    )).all()) if assignees else {}
    return [LeadReminderResponse(
        id=lead.id, company_name=lead.company_name, contact_name=lead.contact_name,
        next_followup_date=lead.next_followup_date, next_followup_notes=lead.next_followup_notes,
        status=lead.status, assigned_user_name=names.get(lead.assigned_to),
        days_until_followup=(lead.next_followup_date - date_).days,
    ) for lead in leads]


# --- CRUD ---

@router.get("", response_model=list[LeadResponse])
async def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    service_interest: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    query = select(Lead).options(selectinload(Lead.assigned_user))
    # IDOR: workers only see their assigned leads
    if current_user.role != UserRole.admin:
        query = query.where(Lead.assigned_to == current_user.id)

    if status_filter:
        query = query.where(Lead.status == status_filter)
    if source:
        query = query.where(Lead.source == source)
    if assigned_to is not None:
        query = query.where(Lead.assigned_to == assigned_to)
    if service_interest:
        query = query.where(Lead.service_interest == service_interest)

    query = query.order_by(Lead.updated_at.desc())
    result = await db.execute(query)
    leads = result.scalars().all()
    return [_lead_to_response(l) for l in leads]


@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    data: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    lead = Lead(
        company_name=data.company_name,
        contact_name=data.contact_name,
        email=data.email,
        phone=data.phone,
        website=data.website,
        linkedin_url=data.linkedin_url,
        status=data.status,
        source=data.source,
        assigned_to=data.assigned_to if current_user.role == UserRole.admin else current_user.id,
        estimated_value=data.estimated_value,
        service_interest=data.service_interest,
        currency=data.currency,
        notes=data.notes,
        industry=data.industry,
        company_size=data.company_size,
        current_website_traffic=data.current_website_traffic,
        next_followup_date=data.next_followup_date,
        next_followup_notes=data.next_followup_notes,
        # Antes se perdían al crear: el formulario los manda y el embudo los usa.
        estimated_close_date=data.estimated_close_date,
        probability=data.probability,
    )
    db.add(lead)
    await db.flush()
    lead_pipeline.record_status(db, lead, lead.status)
    await lead_pipeline.notify_new_lead(db, lead, created_by=current_user.id,
                                        origin=f"Lo ha creado {current_user.full_name}")
    await db.commit()
    await safe_refresh(db, lead, log_context="leads")
    # Reload with relationship for response
    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead.id)
        .options(selectinload(Lead.assigned_user))
    )
    return _lead_to_response(lead_result.scalar_one())


@router.get("/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    result = await db.execute(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.assigned_user),
            selectinload(Lead.activities).selectinload(LeadActivity.user),
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # IDOR check
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")

    resp = _lead_to_response(lead)
    activities = [_activity_to_response(a) for a in (lead.activities or [])]
    return LeadDetailResponse(**resp.model_dump(), activities=activities)


_UPDATABLE_LEAD_FIELDS = {
    "company_name", "contact_name", "email", "phone", "website",
    "linkedin_url", "status", "source", "assigned_to",
    "estimated_value", "service_interest", "currency", "notes",
    "industry", "company_size", "current_website_traffic",
    "next_followup_date", "next_followup_notes", "last_contacted_at",
    "lost_reason", "estimated_close_date", "probability",
}


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")

    old_status = lead.status
    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key not in _UPDATABLE_LEAD_FIELDS:
            continue
        setattr(lead, key, value)

    # Auto-create status_change activity
    if "status" in update_data and update_data["status"] != old_status:
        activity = LeadActivity(
            lead_id=lead.id,
            user_id=current_user.id,
            activity_type=LeadActivityType.status_change,
            title=f"Estado cambiado: {_status_label(old_status.value)} → {_status_label(update_data['status'].value if hasattr(update_data['status'], 'value') else update_data['status'])}",
        )
        db.add(activity)
        lead_pipeline.record_status(db, lead, LeadStatus(update_data["status"]))

    await db.commit()
    await safe_refresh(db, lead, log_context="leads")
    # Reload with relationship for response
    lead_result = await db.execute(
        select(Lead).where(Lead.id == lead.id)
        .options(selectinload(Lead.assigned_user))
    )
    return _lead_to_response(lead_result.scalar_one())


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Solo admin puede eliminar leads")
    # Delete associated activities first (FK constraint)
    await db.execute(
        select(LeadActivity).where(LeadActivity.lead_id == lead_id)
    )
    activities = (await db.execute(
        select(LeadActivity).where(LeadActivity.lead_id == lead_id)
    )).scalars().all()
    for a in activities:
        await db.delete(a)
    await db.delete(lead)
    await db.commit()


# --- Activities ---

@router.post("/{lead_id}/activities", response_model=LeadActivityResponse, status_code=status.HTTP_201_CREATED)
async def add_activity(
    lead_id: int,
    data: LeadActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")

    activity = LeadActivity(
        lead_id=lead_id,
        user_id=current_user.id,
        activity_type=data.activity_type,
        title=data.title,
        description=data.description,
    )
    db.add(activity)

    # Update last_contacted_at for contact activities
    if data.activity_type in (
        LeadActivityType.email_sent, LeadActivityType.call,
        LeadActivityType.meeting, LeadActivityType.email_received,
    ):
        lead.last_contacted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await safe_refresh(db, activity, log_context="leads")
    # Reload with user relationship for response
    act_result = await db.execute(
        select(LeadActivity).where(LeadActivity.id == activity.id)
        .options(selectinload(LeadActivity.user))
    )
    return _activity_to_response(act_result.scalar_one())


# --- Convert to Client ---

@router.post("/{lead_id}/convert", response_model=dict)
async def convert_to_client(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")
    if lead.status == LeadStatus.lost:
        raise HTTPException(status_code=400, detail="No se puede convertir un lead perdido")
    if lead.status == LeadStatus.won:
        raise HTTPException(status_code=400, detail="Este lead ya fue convertido")
    if lead.converted_client_id:
        raise HTTPException(status_code=400, detail="Este lead ya tiene un cliente asociado")

    # Create new client
    client = Client(
        name=lead.company_name,
        email=lead.email,
        phone=lead.phone,
        company=lead.company_name,
        website=lead.website,
        contract_type=ContractType.monthly,
        status=ClientStatus.active,
        notes=f"Convertido desde lead. Servicio: {lead.service_interest or 'N/A'}. Valor estimado: {lead.estimated_value or 'N/A'} {lead.currency}",
        currency=lead.currency,
    )
    db.add(client)
    await db.flush()

    # Update lead
    lead.status = LeadStatus.won
    lead_pipeline.record_status(db, lead, LeadStatus.won)
    lead.converted_client_id = client.id
    lead.converted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create status_change activity
    activity = LeadActivity(
        lead_id=lead.id,
        user_id=current_user.id,
        activity_type=LeadActivityType.status_change,
        title=f"Lead convertido a cliente: {client.name}",
        description=f"Cliente creado con ID {client.id}",
    )
    db.add(activity)

    await db.commit()
    await safe_refresh(db, client, log_context="leads")

    return {
        "message": "Lead convertido a cliente exitosamente",
        "client_id": client.id,
        "client_name": client.name,
    }
