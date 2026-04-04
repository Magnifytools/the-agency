"""Proposals CRUD operations, status changes, duplicate, convert, and AI generation."""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Optional
from datetime import datetime, date, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import (
    Proposal, Client, Project, User, Lead, ServiceTemplate,
    ProposalStatus, ServiceType, ProjectStatus, UserRole,
)
from backend.api.deps import get_current_user, require_module, require_admin
from backend.schemas.proposal import (
    ProposalCreate, ProposalUpdate, ProposalResponse,
    ProposalStatusUpdate,
)
from backend.services.ai_utils import get_anthropic_client, parse_claude_json
from backend.core.rate_limiter import ai_limiter
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/proposals", tags=["proposals"])
logger = logging.getLogger(__name__)


def _to_response(prop: Proposal) -> dict[str, Any]:
    """Convert a Proposal ORM object to a response dict."""
    # Build pricing_options safely
    pricing = None
    if prop.pricing_options:
        pricing = prop.pricing_options if isinstance(prop.pricing_options, list) else None

    return {
        "id": prop.id,
        "title": prop.title,
        "lead_id": prop.lead_id,
        "client_id": prop.client_id,
        "created_by": prop.created_by,
        "contact_name": prop.contact_name,
        "company_name": prop.company_name or "",
        "service_type": prop.service_type.value if prop.service_type else None,
        "situation": prop.situation,
        "problem": prop.problem,
        "cost_of_inaction": prop.cost_of_inaction,
        "opportunity": prop.opportunity,
        "approach": prop.approach,
        "relevant_cases": prop.relevant_cases,
        "pricing_options": pricing,
        "internal_hours_david": float(prop.internal_hours_david) if prop.internal_hours_david else None,
        "internal_hours_nacho": float(prop.internal_hours_nacho) if prop.internal_hours_nacho else None,
        "internal_cost_estimate": float(prop.internal_cost_estimate) if prop.internal_cost_estimate else None,
        "estimated_margin_percent": float(prop.estimated_margin_percent) if prop.estimated_margin_percent else None,
        "generated_content": prop.generated_content,
        "status": prop.status.value,
        "sent_at": prop.sent_at,
        "responded_at": prop.responded_at,
        "response_notes": prop.response_notes,
        "valid_until": prop.valid_until.isoformat() if prop.valid_until else None,
        "converted_project_id": prop.converted_project_id,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
        # Denormalized
        "client_name": prop.client.name if prop.client else None,
        "lead_company": prop.lead.company_name if prop.lead else None,
        "created_by_name": prop.created_by_user.full_name if prop.created_by_user else None,
    }


# ── CRUD ───────────────────────────────────────────────────


@router.get("", response_model=list[ProposalResponse])
async def list_proposals(
    status_filter: Optional[ProposalStatus] = Query(None, alias="status"),
    lead_id: Optional[int] = Query(None),
    client_id: Optional[int] = Query(None),
    service_type: Optional[ServiceType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    query = select(Proposal)
    if status_filter:
        query = query.where(Proposal.status == status_filter)
    if lead_id:
        query = query.where(Proposal.lead_id == lead_id)
    if client_id:
        query = query.where(Proposal.client_id == client_id)
    if service_type:
        query = query.where(Proposal.service_type == service_type)
    query = query.options(
        selectinload(Proposal.client),
        selectinload(Proposal.lead),
        selectinload(Proposal.created_by_user),
    )
    query = query.order_by(Proposal.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return [_to_response(p) for p in result.scalars().all()]


@router.post("", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    data: ProposalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals", write=True)),
):
    # Build proposal from data
    dump = data.model_dump(exclude_unset=True)

    # Convert pricing_options to plain dicts for JSON storage
    if "pricing_options" in dump and dump["pricing_options"]:
        dump["pricing_options"] = [
            p.model_dump() if hasattr(p, "model_dump") else p
            for p in (data.pricing_options or [])
        ]

    dump["created_by"] = current_user.id

    # Default valid_until to 30 days from now
    if "valid_until" not in dump or dump["valid_until"] is None:
        dump["valid_until"] = date.today() + timedelta(days=30)

    new_prop = Proposal(**dump)
    db.add(new_prop)
    await db.commit()
    await safe_refresh(db, new_prop, log_context="proposals")

    # Reload with relations
    result = await db.execute(
        select(Proposal)
        .where(Proposal.id == new_prop.id)
        .options(
            selectinload(Proposal.client),
            selectinload(Proposal.lead),
            selectinload(Proposal.created_by_user),
        )
    )
    return _to_response(result.scalar_one())


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    result = await db.execute(
        select(Proposal)
        .where(Proposal.id == proposal_id)
        .options(
            selectinload(Proposal.client),
            selectinload(Proposal.lead),
            selectinload(Proposal.created_by_user),
        )
    )
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    return _to_response(prop)


_UPDATABLE_PROPOSAL_FIELDS = {
    "title", "lead_id", "client_id", "contact_name", "company_name",
    "service_type", "situation", "problem", "cost_of_inaction",
    "opportunity", "approach", "relevant_cases", "pricing_options",
    "internal_hours_david", "internal_hours_nacho",
    "internal_cost_estimate", "estimated_margin_percent",
    "generated_content", "valid_until", "status", "response_notes",
}


@router.put("/{proposal_id}", response_model=ProposalResponse)
async def update_proposal(
    proposal_id: int,
    data: ProposalUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals", write=True)),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    update_data = data.model_dump(exclude_unset=True)

    # Convert pricing_options for JSON
    if "pricing_options" in update_data and update_data["pricing_options"]:
        update_data["pricing_options"] = [
            p.model_dump() if hasattr(p, "model_dump") else p
            for p in (data.pricing_options or [])
        ]

    for key, value in update_data.items():
        if key not in _UPDATABLE_PROPOSAL_FIELDS:
            continue
        setattr(prop, key, value)

    await db.commit()
    await safe_refresh(db, prop, log_context="proposals")

    result = await db.execute(
        select(Proposal).where(Proposal.id == prop.id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    return _to_response(result.scalar_one())


@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals", write=True)),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if prop.status != ProposalStatus.draft:
        raise HTTPException(status_code=400, detail="Solo se pueden borrar borradores")
    await db.delete(prop)
    await db.commit()


# ── Status change ──────────────────────────────────────────


@router.put("/{proposal_id}/status", response_model=ProposalResponse)
async def change_proposal_status(
    proposal_id: int,
    body: ProposalStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals", write=True)),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    prop.status = body.status

    if body.status == ProposalStatus.sent:
        prop.sent_at = now
    elif body.status in (ProposalStatus.accepted, ProposalStatus.rejected):
        prop.responded_at = now
        if body.response_notes:
            prop.response_notes = body.response_notes

    await db.commit()
    await safe_refresh(db, prop, log_context="proposals")

    result = await db.execute(
        select(Proposal).where(Proposal.id == prop.id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    return _to_response(result.scalar_one())


# ── Duplicate ──────────────────────────────────────────────


@router.post("/{proposal_id}/duplicate", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals", write=True)),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    new_prop = Proposal(
        title=f"{original.title} (copia)",
        lead_id=original.lead_id,
        client_id=original.client_id,
        created_by=current_user.id,
        contact_name=original.contact_name,
        company_name=original.company_name,
        service_type=original.service_type,
        situation=original.situation,
        problem=original.problem,
        cost_of_inaction=original.cost_of_inaction,
        opportunity=original.opportunity,
        approach=original.approach,
        relevant_cases=original.relevant_cases,
        pricing_options=original.pricing_options,
        internal_hours_david=original.internal_hours_david,
        internal_hours_nacho=original.internal_hours_nacho,
        internal_cost_estimate=original.internal_cost_estimate,
        estimated_margin_percent=original.estimated_margin_percent,
        generated_content=original.generated_content,
        status=ProposalStatus.draft,
        valid_until=date.today() + timedelta(days=30),
    )
    db.add(new_prop)
    await db.commit()
    await safe_refresh(db, new_prop, log_context="proposals")

    result = await db.execute(
        select(Proposal).where(Proposal.id == new_prop.id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    return _to_response(result.scalar_one())


# ── Convert to project ─────────────────────────────────────


@router.post("/{proposal_id}/convert", response_model=ProposalResponse)
async def convert_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Convert an accepted proposal into a client + project."""
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if prop.status != ProposalStatus.accepted:
        raise HTTPException(status_code=400, detail="Solo se pueden convertir propuestas aceptadas")
    if prop.converted_project_id:
        raise HTTPException(status_code=400, detail="Esta propuesta ya fue convertida")

    # If from lead and no client yet, create client from lead
    client_id = prop.client_id
    if prop.lead_id and not client_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == prop.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead and not lead.converted_client_id:
            new_client = Client(
                name=lead.company_name,
                email=lead.email,
                notes=f"Contacto: {lead.contact_name}" if lead.contact_name else None,
            )
            db.add(new_client)
            await db.flush()
            client_id = new_client.id
            lead.converted_client_id = new_client.id
            prop.client_id = client_id
        elif lead and lead.converted_client_id:
            client_id = lead.converted_client_id
            prop.client_id = client_id

    if not client_id:
        # Create client from proposal data
        new_client = Client(
            name=prop.company_name or "Cliente sin nombre",
            notes=f"Contacto: {prop.contact_name}" if prop.contact_name else None,
        )
        db.add(new_client)
        await db.flush()
        client_id = new_client.id
        prop.client_id = client_id

    # Get recommended pricing for project budget
    budget = None
    if prop.pricing_options:
        for opt in prop.pricing_options:
            if isinstance(opt, dict) and opt.get("recommended"):
                budget = opt.get("price")
                break
        if not budget and prop.pricing_options:
            first = prop.pricing_options[0]
            budget = first.get("price") if isinstance(first, dict) else None

    # Create project
    project = Project(
        name=prop.title,
        description=prop.approach or "",
        client_id=client_id,
        project_type=prop.service_type.value if prop.service_type else "custom",
        status=ProjectStatus.active,
        budget_amount=budget,
    )
    db.add(project)
    await db.flush()

    prop.converted_project_id = project.id
    await db.commit()
    await safe_refresh(db, prop, log_context="proposals")

    result = await db.execute(
        select(Proposal).where(Proposal.id == prop.id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    return _to_response(result.scalar_one())


# ── AI Generation ──────────────────────────────────────────


@router.post("/{proposal_id}/generate", response_model=ProposalResponse)
async def generate_proposal_content(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals", write=True)),
):
    """Generate proposal content using Claude API."""
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=300)

    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    # Load service template for context
    template_context = ""
    service_name = "Personalizado"
    phases_info = ""
    includes_info = ""
    excludes_info = ""

    if prop.service_type:
        tmpl_result = await db.execute(
            select(ServiceTemplate).where(ServiceTemplate.service_type == prop.service_type)
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl:
            template_context = tmpl.prompt_context or ""
            service_name = tmpl.name
            if tmpl.default_phases:
                phases_info = "\n".join(
                    f"- {p['name']} ({p['duration']}): {p['outcome']}"
                    for p in tmpl.default_phases
                )
            includes_info = tmpl.default_includes or ""
            excludes_info = tmpl.default_excludes or ""

    # Build pricing string
    pricing_str = ""
    if prop.pricing_options:
        for opt in prop.pricing_options:
            if isinstance(opt, dict):
                rec = " RECOMENDADA" if opt.get("recommended") else ""
                recurring = "/mes" if opt.get("is_recurring") else ""
                pricing_str += f"- {opt['name']}: {opt.get('price', 0)}EUR{recurring}{rec} -- {opt.get('description', '')}\n"

    # Enrich prompt with client revenue fields when available
    client_context = ""
    if prop.client_id:
        client_result = await db.execute(select(Client).where(Client.id == prop.client_id))
        client_obj = client_result.scalar_one_or_none()
        if client_obj:
            fields = []
            if client_obj.business_model:
                fields.append(f"- Modelo de negocio: {client_obj.business_model}")
            if client_obj.aov:
                fields.append(f"- Valor medio de pedido (AOV): {client_obj.aov}EUR")
            if client_obj.conversion_rate:
                fields.append(f"- Tasa de conversion: {client_obj.conversion_rate}%")
            if client_obj.ltv:
                fields.append(f"- Valor de vida del cliente (LTV): {client_obj.ltv}EUR")
            if client_obj.seo_maturity_level:
                fields.append(f"- Madurez SEO: {client_obj.seo_maturity_level}")
            if fields:
                client_context = "\n\nDATOS DE NEGOCIO DEL CLIENTE:\n" + "\n".join(fields)
                client_context += "\nUsa estos datos para hacer estimaciones de ROI mas especificas en la propuesta."

    prompt = f"""Eres el redactor de propuestas de Magnify, una consultora SEO boutique en Barcelona dirigida por David Carrasco. Generas propuestas de servicios SEO profesionales, directas y centradas en el impacto de negocio del cliente.

REGLAS ESTRICTAS:
- NUNCA mencionar horas de trabajo. Jamas.
- NUNCA usar jerga SEO excesiva. El cliente es un directivo, no un tecnico.
- Maximo 4 paginas equivalentes de contenido.
- Tono: profesional pero humano. Directo. Sin corporate-speak.
- Idioma: espanol de Espana.
- Las frases deben ser cortas y claras. Nada de parrafos de 6 lineas.

DATOS DE LA PROPUESTA:
- Empresa: {prop.company_name}
- Contacto: {prop.contact_name or 'No especificado'}
- Tipo de servicio: {prop.service_type.value if prop.service_type else 'custom'} -- {service_name}
- Contexto del servicio: {template_context}
- Situacion del cliente: {prop.situation or 'No especificada'}
- Problema identificado: {prop.problem or 'No especificado'}
- Coste de no actuar: {prop.cost_of_inaction or 'No especificado'}
- Oportunidad: {prop.opportunity or 'No especificada'}
- Enfoque propuesto: {prop.approach or 'No especificado'}
- Fases por defecto: {phases_info or 'Personalizar'}
- Incluye: {includes_info or 'No especificado'}
- No incluye: {excludes_info or 'No especificado'}
- Opciones de precio:
{pricing_str or 'No definidas'}
- Casos relevantes: {prop.relevant_cases or 'No especificados'}{client_context}

GENERA LA PROPUESTA CON ESTA ESTRUCTURA EXACTA en JSON:
{{
  "executive_summary": "Resumen ejecutivo en 3-4 frases. El problema, la oportunidad, y por que Magnify es la mejor opcion.",
  "opening": "Saludo personalizado + referencia a la conversacion. 2-3 frases maximo.",
  "situation": "Situacion actual del cliente. 1 parrafo.",
  "problem": "El problema REAL de negocio. Directo, sin rodeos. 1 parrafo.",
  "cost_of_inaction": "Que pierde el cliente cada mes/ano sin actuar. 1-2 frases.",
  "null_case": "Escenario detallado a 12 meses si el cliente no actua. Datos concretos de perdida de mercado, trafico o ingresos. 1-2 parrafos.",
  "opportunity": "Que es posible. Especifico y motivador. 1 parrafo.",
  "approach": "Las 2-3 palancas principales explicadas como si hablaras con un CEO. 2-3 parrafos.",
  "phases": [{{"name": "...", "duration": "...", "outcome": "Que cambia al terminar esta fase."}}],
  "includes": "Que incluye el servicio. Parrafo breve.",
  "excludes": "Que no incluye. Parrafo breve.",
  "success_metrics": [{{"metric": "Nombre del KPI", "current": "Valor actual estimado", "target_12m": "Objetivo a 12 meses", "impact": "Impacto en negocio"}}],
  "credibility": "2-3 lineas sobre Magnify. Nombres de empresas reconocibles.",
  "cases": "1-2 mini-casos de 2 lineas cada uno.",
  "next_steps": "3 pasos concretos con fechas tentativas."
}}

Responde SOLO con el JSON, sin markdown ni texto adicional."""

    try:
        client = get_anthropic_client()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        message = await asyncio.wait_for(
            client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=55,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="La IA tardo demasiado en responder")

    try:
        generated = parse_claude_json(message)
    except ValueError:
        logger.exception("Invalid AI JSON while generating proposal id=%s", proposal_id)
        raise HTTPException(status_code=502, detail="La IA devolvio un formato no valido")

    prop.generated_content = generated
    await db.commit()
    await safe_refresh(db, prop, log_context="proposals")

    result = await db.execute(
        select(Proposal).where(Proposal.id == prop.id)
        .options(selectinload(Proposal.client), selectinload(Proposal.lead), selectinload(Proposal.created_by_user))
    )
    return _to_response(result.scalar_one())
