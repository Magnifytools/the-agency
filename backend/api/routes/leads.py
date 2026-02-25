"""CRM Leads — Pipeline de ventas."""
from __future__ import annotations

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func as sa_func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Lead, LeadActivity, LeadStatus, LeadSource, LeadActivityType,
    Client, ClientStatus, ContractType, User, UserRole,
)
from backend.api.deps import get_current_user, require_module
from backend.schemas.lead import (
    LeadCreate, LeadUpdate, LeadResponse, LeadDetailResponse,
    LeadActivityCreate, LeadActivityResponse,
    PipelineSummary, PipelineStageSummary,
    LeadReminderResponse,
)

router = APIRouter(prefix="/api/leads", tags=["leads"])


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
    current_user: User = Depends(require_module("leads")),
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

    return PipelineSummary(stages=stages, total_leads=total_leads, total_value=total_value)


# --- Reminders ---

@router.get("/reminders", response_model=list[LeadReminderResponse])
async def lead_reminders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads")),
):
    today = date.today()
    threshold = today + timedelta(days=3)

    query = select(Lead).where(
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


# --- CRUD ---

@router.get("", response_model=list[LeadResponse])
async def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    service_interest: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads")),
):
    query = select(Lead)
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
    current_user: User = Depends(require_module("leads", write=True)),
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
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return _lead_to_response(lead)


@router.get("/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads")),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # IDOR check
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")

    resp = _lead_to_response(lead)
    activities = [_activity_to_response(a) for a in (lead.activities or [])]
    return LeadDetailResponse(**resp.model_dump(), activities=activities)


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads", write=True)),
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
        setattr(lead, key, value)

    # Auto-create status_change activity
    if "status" in update_data and update_data["status"] != old_status:
        activity = LeadActivity(
            lead_id=lead.id,
            user_id=current_user.id,
            activity_type=LeadActivityType.status_change,
            title=f"Estado cambiado: {old_status.value} → {update_data['status'].value if hasattr(update_data['status'], 'value') else update_data['status']}",
        )
        db.add(activity)

    await db.commit()
    await db.refresh(lead)
    return _lead_to_response(lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Solo admin puede eliminar leads")
    await db.delete(lead)
    await db.commit()


# --- Activities ---

@router.post("/{lead_id}/activities", response_model=LeadActivityResponse, status_code=status.HTTP_201_CREATED)
async def add_activity(
    lead_id: int,
    data: LeadActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads", write=True)),
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
        lead.last_contacted_at = datetime.utcnow()

    await db.commit()
    await db.refresh(activity)
    return _activity_to_response(activity)


# --- Convert to Client ---

@router.post("/{lead_id}/convert", response_model=dict)
async def convert_to_client(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("leads", write=True)),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if current_user.role != UserRole.admin and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")
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
    lead.converted_client_id = client.id
    lead.converted_at = datetime.utcnow()

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
    await db.refresh(client)

    return {
        "message": "Lead convertido a cliente exitosamente",
        "client_id": client.id,
        "client_name": client.name,
    }
