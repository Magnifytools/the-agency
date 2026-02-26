from __future__ import annotations
from typing import Any, Optional
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Environment, BaseLoader

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

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


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
    query = query.order_by(Proposal.created_at.desc())

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
    await db.refresh(new_prop)

    # Reload with relations
    result = await db.execute(select(Proposal).where(Proposal.id == new_prop.id))
    return _to_response(result.scalar_one())


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    return _to_response(prop)


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
        setattr(prop, key, value)

    await db.commit()
    await db.refresh(prop)

    result = await db.execute(select(Proposal).where(Proposal.id == prop.id))
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

    now = datetime.utcnow()
    prop.status = body.status

    if body.status == ProposalStatus.sent:
        prop.sent_at = now
    elif body.status in (ProposalStatus.accepted, ProposalStatus.rejected):
        prop.responded_at = now
        if body.response_notes:
            prop.response_notes = body.response_notes

    await db.commit()
    await db.refresh(prop)

    result = await db.execute(select(Proposal).where(Proposal.id == prop.id))
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
    await db.refresh(new_prop)

    result = await db.execute(select(Proposal).where(Proposal.id == new_prop.id))
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
    await db.refresh(prop)

    result = await db.execute(select(Proposal).where(Proposal.id == prop.id))
    return _to_response(result.scalar_one())


# ── AI Generation ──────────────────────────────────────────


@router.post("/{proposal_id}/generate", response_model=ProposalResponse)
async def generate_proposal_content(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals", write=True)),
):
    """Generate proposal content using Claude API."""
    from backend.config import settings

    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY no configurada")

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
                rec = " ⭐ RECOMENDADA" if opt.get("recommended") else ""
                recurring = "/mes" if opt.get("is_recurring") else ""
                pricing_str += f"- {opt['name']}: {opt.get('price', 0)}€{recurring}{rec} — {opt.get('description', '')}\n"

    prompt = f"""Eres el redactor de propuestas de Magnify, una consultora SEO boutique en Barcelona dirigida por David Carrasco. Generas propuestas de servicios SEO profesionales, directas y centradas en el impacto de negocio del cliente.

REGLAS ESTRICTAS:
- NUNCA mencionar horas de trabajo. Jamás.
- NUNCA usar jerga SEO excesiva. El cliente es un directivo, no un técnico.
- Máximo 4 páginas equivalentes de contenido.
- Tono: profesional pero humano. Directo. Sin corporate-speak.
- Idioma: español de España.
- Las frases deben ser cortas y claras. Nada de párrafos de 6 líneas.

DATOS DE LA PROPUESTA:
- Empresa: {prop.company_name}
- Contacto: {prop.contact_name or 'No especificado'}
- Tipo de servicio: {prop.service_type.value if prop.service_type else 'custom'} — {service_name}
- Contexto del servicio: {template_context}
- Situación del cliente: {prop.situation or 'No especificada'}
- Problema identificado: {prop.problem or 'No especificado'}
- Coste de no actuar: {prop.cost_of_inaction or 'No especificado'}
- Oportunidad: {prop.opportunity or 'No especificada'}
- Enfoque propuesto: {prop.approach or 'No especificado'}
- Fases por defecto: {phases_info or 'Personalizar'}
- Incluye: {includes_info or 'No especificado'}
- No incluye: {excludes_info or 'No especificado'}
- Opciones de precio:
{pricing_str or 'No definidas'}
- Casos relevantes: {prop.relevant_cases or 'No especificados'}

GENERA LA PROPUESTA CON ESTA ESTRUCTURA EXACTA en JSON:
{{
  "opening": "Saludo personalizado + referencia a la conversación. 2-3 frases máximo.",
  "situation": "Situación actual del cliente. 1 párrafo.",
  "problem": "El problema REAL de negocio. Directo, sin rodeos. 1 párrafo.",
  "cost_of_inaction": "Qué pierde el cliente cada mes/año sin actuar. 1-2 frases.",
  "opportunity": "Qué es posible. Específico y motivador. 1 párrafo.",
  "approach": "Las 2-3 palancas principales explicadas como si hablaras con un CEO. 2-3 párrafos.",
  "phases": [{{"name": "...", "duration": "...", "outcome": "Qué cambia al terminar esta fase."}}],
  "includes": "Qué incluye el servicio. Párrafo breve.",
  "excludes": "Qué no incluye. Párrafo breve.",
  "credibility": "2-3 líneas sobre Magnify. Nombres de empresas reconocibles.",
  "cases": "1-2 mini-casos de 2 líneas cada uno.",
  "next_steps": "3 pasos concretos con fechas tentativas."
}}

Responde SOLO con el JSON, sin markdown ni texto adicional."""

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    try:
        content_text = message.content[0].text
        # Strip markdown code blocks if present
        if content_text.startswith("```"):
            content_text = content_text.split("\n", 1)[1]
            content_text = content_text.rsplit("```", 1)[0]
        generated = json.loads(content_text)
    except (json.JSONDecodeError, IndexError) as e:
        raise HTTPException(status_code=500, detail=f"Error parseando respuesta de IA: {str(e)}")

    prop.generated_content = generated
    await db.commit()
    await db.refresh(prop)

    result = await db.execute(select(Proposal).where(Proposal.id == prop.id))
    return _to_response(result.scalar_one())


# ── PDF Generation ─────────────────────────────────────────


PDF_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
    <style>
        @page { size: A4; margin: 25mm 20mm 20mm 20mm; }
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #222; line-height: 1.6; margin: 0; font-size: 11pt; }
        .page-break { page-break-before: always; }

        /* Header */
        .header { border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-bottom: 15px; }
        .header-text { font-size: 10pt; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; }

        /* Cover */
        .cover { text-align: center; padding-top: 120px; }
        .cover-logo { font-size: 28pt; font-weight: 800; letter-spacing: 4px; margin-bottom: 60px; }
        .cover-title { font-size: 20pt; font-weight: 300; margin-bottom: 10px; }
        .cover-company { font-size: 16pt; font-weight: 600; margin-bottom: 40px; }
        .cover-date { font-size: 10pt; color: #666; }

        /* Content */
        h2 { font-size: 14pt; margin-top: 25px; margin-bottom: 10px; color: #111; border-bottom: 1px solid #ddd; padding-bottom: 5px; }
        p { margin: 8px 0; }

        /* Phases */
        .phase { background: #f5f5f5; padding: 12px 15px; margin: 8px 0; border-left: 3px solid #333; border-radius: 0 4px 4px 0; }
        .phase-name { font-weight: 700; }
        .phase-duration { color: #666; font-size: 9pt; }
        .phase-outcome { margin-top: 4px; font-size: 10pt; }

        /* Pricing */
        .pricing-option { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 6px; }
        .pricing-option.recommended { border-color: #333; border-width: 2px; background: #fafafa; }
        .pricing-name { font-size: 13pt; font-weight: 700; }
        .pricing-price { font-size: 18pt; font-weight: 800; margin: 8px 0; }
        .pricing-desc { font-size: 10pt; color: #555; }
        .pricing-ideal { font-size: 9pt; color: #888; font-style: italic; }
        .pricing-badge { display: inline-block; background: #333; color: #fff; font-size: 8pt; padding: 2px 8px; border-radius: 3px; text-transform: uppercase; letter-spacing: 1px; }

        /* Footer */
        .footer { position: fixed; bottom: 0; left: 0; right: 0; text-align: center; font-size: 8pt; color: #999; padding: 10px 0; border-top: 1px solid #eee; }
    </style>
</head>
<body>
    <div class="footer">magnify.ing | david@magnify.ing</div>

    <!-- PAGE 1: COVER -->
    <div class="cover">
        <div class="cover-logo">MAGNIFY</div>
        <div class="cover-title">{{ service_label }}</div>
        <div class="cover-company">{{ company_name }}</div>
        <div class="cover-date">{{ date_str }}</div>
    </div>

    <!-- PAGE 2: SITUATION & OPPORTUNITY -->
    <div class="page-break"></div>
    <div class="header"><span class="header-text">MAGNIFY</span></div>

    {% if content.opening %}
    <p>{{ content.opening }}</p>
    {% endif %}

    {% if content.situation %}
    <h2>Situación actual</h2>
    <p>{{ content.situation }}</p>
    {% endif %}

    {% if content.problem %}
    <h2>El reto</h2>
    <p>{{ content.problem }}</p>
    {% endif %}

    {% if content.cost_of_inaction %}
    <p><strong>{{ content.cost_of_inaction }}</strong></p>
    {% endif %}

    {% if content.opportunity %}
    <h2>La oportunidad</h2>
    <p>{{ content.opportunity }}</p>
    {% endif %}

    <!-- PAGE 3: PROPOSAL -->
    <div class="page-break"></div>
    <div class="header"><span class="header-text">MAGNIFY</span></div>

    {% if content.approach %}
    <h2>Nuestra propuesta</h2>
    <p>{{ content.approach }}</p>
    {% endif %}

    {% if content.phases %}
    <h2>Fases del proyecto</h2>
    {% for phase in content.phases %}
    <div class="phase">
        <div class="phase-name">{{ phase.name }}</div>
        <div class="phase-duration">{{ phase.duration }}</div>
        <div class="phase-outcome">→ {{ phase.outcome }}</div>
    </div>
    {% endfor %}
    {% endif %}

    {% if content.includes %}
    <h2>Qué incluye</h2>
    <p>{{ content.includes }}</p>
    {% endif %}

    {% if content.excludes %}
    <h2>Qué no incluye</h2>
    <p>{{ content.excludes }}</p>
    {% endif %}

    <!-- PAGE 4: PRICING & CREDIBILITY -->
    <div class="page-break"></div>
    <div class="header"><span class="header-text">MAGNIFY</span></div>

    <h2>Inversión</h2>
    {% for opt in pricing %}
    <div class="pricing-option {{ 'recommended' if opt.recommended else '' }}">
        {% if opt.recommended %}<span class="pricing-badge">Recomendada</span>{% endif %}
        <div class="pricing-name">{{ opt.name }}</div>
        <div class="pricing-price">{{ "{:,.0f}".format(opt.price).replace(",", ".") }} €{{ "/mes" if opt.is_recurring else "" }}</div>
        <div class="pricing-desc">{{ opt.description }}</div>
        {% if opt.ideal_for %}<div class="pricing-ideal">Ideal para: {{ opt.ideal_for }}</div>{% endif %}
    </div>
    {% endfor %}

    <p style="font-size: 9pt; color: #666; margin-top: 15px;">
        Proyectos: 50% al inicio, 50% a la entrega. Retainers: mensual, sin permanencia, 30 días de aviso.
    </p>

    {% if content.credibility %}
    <h2>Sobre Magnify</h2>
    <p>{{ content.credibility }}</p>
    {% endif %}

    {% if content.cases %}
    <p>{{ content.cases }}</p>
    {% endif %}

    {% if content.next_steps %}
    <h2>Siguientes pasos</h2>
    <p>{{ content.next_steps }}</p>
    {% endif %}

    <p style="margin-top: 30px; font-size: 10pt;">
        <strong>David Carrasco</strong><br>
        david@magnify.ing<br>
        magnify.ing
    </p>
</body>
</html>
"""


@router.post("/{proposal_id}/generate-pdf")
async def generate_proposal_pdf(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    """Generate a print-ready HTML page for the proposal.

    Returns HTML that the browser can print/save as PDF via Ctrl+P.
    The page includes @media print styles for clean A4 output.
    """
    return await _render_proposal_html(proposal_id, db)


@router.get("/{proposal_id}/pdf")
async def get_proposal_pdf(
    proposal_id: int,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Render proposal as print-ready HTML. Accepts auth via query param for new-tab usage."""
    from backend.core.security import decode_access_token

    if token:
        payload = decode_access_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        raise HTTPException(status_code=401, detail="Token required")

    return await _render_proposal_html(proposal_id, db)


async def _render_proposal_html(proposal_id: int, db: AsyncSession) -> Response:
    """Render proposal as print-ready HTML page."""
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    content = prop.generated_content or {}
    pricing = prop.pricing_options or []
    pricing_safe = []
    for p in pricing:
        if isinstance(p, dict):
            pricing_safe.append({
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "ideal_for": p.get("ideal_for", ""),
                "price": p.get("price", 0),
                "is_recurring": p.get("is_recurring", False),
                "recommended": p.get("recommended", False),
            })

    service_labels = {
        "seo_sprint": "SEO Sprint — Puesta a punto",
        "migration": "Supervisión de migración web",
        "market_study": "Estudio estratégico de mercado SEO",
        "consulting_retainer": "Consultoría SEO estratégica",
        "partnership_retainer": "Partnership SEO integral",
        "brand_audit": "Brand Visibility Audit",
        "custom": "Propuesta personalizada",
    }
    service_label = service_labels.get(
        prop.service_type.value if prop.service_type else "custom",
        "Propuesta de servicios"
    )

    env = Environment(loader=BaseLoader(), autoescape=True)
    template = env.from_string(PDF_HTML_TEMPLATE)
    html_content = template.render(
        title=prop.title,
        company_name=prop.company_name or "Cliente",
        service_label=service_label,
        date_str=(prop.created_at or datetime.utcnow()).strftime("%d de %B de %Y"),
        content=content,
        pricing=pricing_safe,
    )

    return Response(
        content=html_content,
        media_type="text/html",
    )
