"""Proposals PDF generation, HTML rendering, and email sending."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from jinja2 import Environment, BaseLoader

from backend.db.database import get_db
from backend.db.models import Proposal, User, ProposalStatus
from backend.api.deps import require_module
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/proposals", tags=["proposals"])
logger = logging.getLogger(__name__)


# ── HTML template for print-ready rendering ──────────────────

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

        /* Executive Summary */
        .exec-summary { background: #f0f4ff; border: 1px solid #c5d4f0; padding: 15px 18px; margin: 15px 0; border-radius: 6px; font-size: 11pt; line-height: 1.7; }

        /* Null Case */
        .null-case { background: #fff8f0; border-left: 3px solid #e67e22; padding: 12px 15px; margin: 12px 0; border-radius: 0 4px 4px 0; }

        /* Success Metrics */
        .metrics-table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9pt; }
        .metrics-table th { background: #f5f5f5; padding: 8px 10px; text-align: left; border-bottom: 2px solid #ddd; font-weight: 700; }
        .metrics-table td { padding: 8px 10px; border-bottom: 1px solid #eee; }

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

    {% if content.executive_summary %}
    <div class="exec-summary">{{ content.executive_summary }}</div>
    {% endif %}

    {% if content.situation %}
    <h2>Situacion actual</h2>
    <p>{{ content.situation }}</p>
    {% endif %}

    {% if content.problem %}
    <h2>El reto</h2>
    <p>{{ content.problem }}</p>
    {% endif %}

    {% if content.cost_of_inaction %}
    <p><strong>{{ content.cost_of_inaction }}</strong></p>
    {% endif %}

    {% if content.null_case %}
    <div class="null-case">
        <strong>Si no se actua:</strong> {{ content.null_case }}
    </div>
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
        <div class="phase-outcome">-> {{ phase.outcome }}</div>
    </div>
    {% endfor %}
    {% endif %}

    {% if content.success_metrics %}
    <h2>Metricas de exito</h2>
    <table class="metrics-table">
        <thead>
            <tr>
                <th>Metrica</th>
                <th>Actual</th>
                <th>Objetivo 12m</th>
                <th>Impacto</th>
            </tr>
        </thead>
        <tbody>
        {% for m in content.success_metrics %}
            <tr>
                <td><strong>{{ m.metric }}</strong></td>
                <td>{{ m.current }}</td>
                <td>{{ m.target_12m }}</td>
                <td>{{ m.impact }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% endif %}

    {% if content.includes %}
    <h2>Que incluye</h2>
    <p>{{ content.includes }}</p>
    {% endif %}

    {% if content.excludes %}
    <h2>Que no incluye</h2>
    <p>{{ content.excludes }}</p>
    {% endif %}

    <!-- PAGE 4: PRICING & CREDIBILITY -->
    <div class="page-break"></div>
    <div class="header"><span class="header-text">MAGNIFY</span></div>

    <h2>Inversion</h2>
    {% for opt in pricing %}
    <div class="pricing-option {{ 'recommended' if opt.recommended else '' }}">
        {% if opt.recommended %}<span class="pricing-badge">Recomendada</span>{% endif %}
        <div class="pricing-name">{{ opt.name }}</div>
        <div class="pricing-price">{{ "{:,.0f}".format(opt.price).replace(",", ".") }} EUR{{ "/mes" if opt.is_recurring else "" }}</div>
        <div class="pricing-desc">{{ opt.description }}</div>
        {% if opt.ideal_for %}<div class="pricing-ideal">Ideal para: {{ opt.ideal_for }}</div>{% endif %}
    </div>
    {% endfor %}

    <p style="font-size: 9pt; color: #666; margin-top: 15px;">
        Proyectos: 50% al inicio, 50% a la entrega. Retainers: mensual, sin permanencia, 30 dias de aviso.
    </p>

    {% if content.investment_model %}
    <h2>Modelo de inversion SEO</h2>
    {% if content.investment_model.summary %}
    <p><strong>Break-even estimado:</strong> mes {{ content.investment_model.summary.break_even_month or 'N/A' }}</p>
    <p><strong>ROI ano 1:</strong> {{ content.investment_model.summary.year1_roi_range or 'N/A' }}</p>
    <p><strong>Ingresos ano 1:</strong> {{ content.investment_model.summary.year1_revenue_range or 'N/A' }}</p>
    {% endif %}
    {% if content.investment_model.scenarios %}
    <table class="metrics-table">
        <thead><tr><th>Escenario</th><th>Trafico nuevo</th><th>Conversiones</th><th>Ingresos</th><th>ROI</th></tr></thead>
        <tbody>
        {% for s in content.investment_model.scenarios %}
        <tr>
            <td><strong>{{ s.label }}</strong></td>
            <td>+{{ s.traffic_increase }}</td>
            <td>+{{ s.new_conversions }}</td>
            <td>{{ s.revenue_increase }}EUR</td>
            <td>{{ s.roi_percent }}%</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    {% endif %}
    {% endif %}

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


# ── PDF builder (fpdf2, pure Python, no system deps) ──────────────────────────

_SERVICE_LABELS = {
    "seo_sprint": "SEO Sprint -- Puesta a punto",
    "migration": "Supervision de migracion web",
    "market_study": "Estudio estrategico de mercado SEO",
    "consulting_retainer": "Consultoria SEO estrategica",
    "partnership_retainer": "Partnership SEO integral",
    "brand_audit": "Brand Visibility Audit",
    "custom": "Propuesta personalizada",
}


def _safe(text: str) -> str:
    """Strip characters outside latin-1 so fpdf2 (built-in fonts) won't crash."""
    # Replace EUR symbol with EUR before encoding
    text = text.replace("\u20ac", "EUR")
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _build_pdf(prop: "Proposal") -> bytes:  # type: ignore[name-defined]
    from fpdf import FPDF

    content = prop.generated_content or {}
    pricing_raw = prop.pricing_options or []
    pricing = [p for p in pricing_raw if isinstance(p, dict)]
    service_label = _SERVICE_LABELS.get(
        prop.service_type.value if prop.service_type else "custom",
        "Propuesta de servicios",
    )
    date_str = (prop.created_at or datetime.now(timezone.utc).replace(tzinfo=None)).strftime("%d/%m/%Y")
    company = _safe(prop.company_name or "Cliente")

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_margins(25, 20, 25)

    # -- Cover --
    pdf.add_page()
    pdf.set_y(80)

    pdf.set_font("Helvetica", "B", 32)
    pdf.cell(0, 12, "MAGNIFY", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 14)
    pdf.cell(0, 8, _safe(service_label), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, company, align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(30)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, date_str, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    # -- Content pages --
    def _header():
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 5, "MAGNIFY", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(30, 30, 30)
        pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
        pdf.ln(4)
        pdf.set_text_color(0, 0, 0)

    def _section(title: str):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _safe(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
        pdf.ln(3)

    def _paragraph(text: str):
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe(str(text)))
        pdf.ln(2)

    def _box(text: str, bg: tuple = (240, 244, 255)):
        pdf.set_fill_color(*bg)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe(str(text)), fill=True, border=1)
        pdf.ln(3)

    pdf.add_page()
    _header()

    for key, label in [
        ("executive_summary", None),
        ("situation", "Situacion actual"),
        ("problem", "El reto"),
        ("opportunity", "La oportunidad"),
    ]:
        val = content.get(key)
        if not val:
            continue
        if label:
            _section(label)
        if key == "executive_summary":
            _box(val)
        else:
            _paragraph(val)

    if content.get("null_case"):
        _box(f"Si no se actua: {content['null_case']}", bg=(255, 248, 240))

    _section("Nuestra propuesta")
    if content.get("approach"):
        _paragraph(content["approach"])

    if content.get("phases"):
        _section("Fases del proyecto")
        for phase in content["phases"]:
            if not isinstance(phase, dict):
                continue
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, _safe(f"{phase.get('name', '')}  --  {phase.get('duration', '')}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            if phase.get("outcome"):
                pdf.cell(0, 5, _safe(f"  -> {phase['outcome']}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    if content.get("success_metrics"):
        _section("Metricas de exito")
        col_w = [50, 30, 35, 55]
        headers = ["Metrica", "Actual", "Objetivo 12m", "Impacto"]
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(245, 245, 245)
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 6, h, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for m in content["success_metrics"]:
            if not isinstance(m, dict):
                continue
            row = [m.get("metric", ""), m.get("current", ""), m.get("target_12m", ""), m.get("impact", "")]
            for i, cell in enumerate(row):
                pdf.cell(col_w[i], 6, _safe(str(cell)), border=1)
            pdf.ln()
        pdf.ln(3)

    for key, label in [
        ("includes", "Que incluye"),
        ("excludes", "Que no incluye"),
    ]:
        val = content.get(key)
        if val:
            _section(label)
            _paragraph(val)

    # -- Pricing page --
    if pricing:
        pdf.add_page()
        _header()
        _section("Inversion")
        for opt in pricing:
            name = _safe(opt.get("name", ""))
            price = opt.get("price", 0)
            recurring = opt.get("is_recurring", False)
            recommended = opt.get("recommended", False)
            desc = _safe(opt.get("description", ""))
            ideal = _safe(opt.get("ideal_for", ""))

            pdf.set_font("Helvetica", "B", 12)
            price_str = f"{price:,.0f}".replace(",", ".") + (" EUR/mes" if recurring else " EUR")
            label_str = f"[RECOMENDADA]  " if recommended else ""
            pdf.cell(0, 7, label_str + name, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 8, price_str, new_x="LMARGIN", new_y="NEXT")
            if desc:
                pdf.set_font("Helvetica", "", 9)
                pdf.multi_cell(0, 5, desc)
            if ideal:
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 5, f"Ideal para: {ideal}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 4, "Proyectos: 50% al inicio, 50% a la entrega. Retainers: mensual, sin permanencia, 30 dias de aviso.")
        pdf.set_text_color(0, 0, 0)

    # -- Investment model --
    inv = content.get("investment_model")
    if inv and isinstance(inv, dict):
        _section("Modelo de inversion")
        scenarios = inv.get("scenarios", [])
        null_sc = inv.get("null_scenario")

        if null_sc and isinstance(null_sc, dict):
            _box(
                f"Sin inversion: trafico cae {null_sc.get('traffic_decline', 0):,} visitas. "
                f"Coste de oportunidad acumulado: {null_sc.get('cumulative_opportunity_cost', 0):,.0f} EUR",
                bg=(255, 235, 235),
            )

        if scenarios:
            col_w = [42, 42, 42, 42]
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(245, 245, 245)
            for i, h in enumerate(["Escenario", "ROI 12m", "Ingresos", "Payback"]):
                pdf.cell(col_w[i], 6, h, border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 9)
            for s in scenarios:
                if not isinstance(s, dict):
                    continue
                row = [
                    s.get("label", ""),
                    f"{s.get('roi_percent', 0)}%",
                    f"{s.get('revenue_increase', 0):,.0f} EUR",
                    f"mes {s.get('payback_months', 'N/A')}" if s.get("payback_months") else "N/A",
                ]
                for i, cell in enumerate(row):
                    pdf.cell(col_w[i], 6, _safe(str(cell)), border=1)
                pdf.ln()
            pdf.ln(3)

        summary = inv.get("summary")
        if summary and isinstance(summary, dict):
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            parts = [f"Break-even: mes {summary.get('break_even_month', 'N/A')}"]
            parts.append(f"ROI: {summary.get('year1_roi_range', '')}")
            parts.append(f"Ingresos: {summary.get('year1_revenue_range', '')}")
            pdf.cell(0, 5, _safe("  |  ".join(parts)), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    for key, label in [
        ("credibility", "Sobre Magnify"),
        ("cases", None),
        ("next_steps", "Siguientes pasos"),
    ]:
        val = content.get(key)
        if not val:
            continue
        if label:
            _section(label)
        _paragraph(val)

    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "David Carrasco", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 4, "david@magnify.ing  |  magnify.ing", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


async def _build_proposal_html(proposal_id: int, db: AsyncSession) -> str:
    """Render the proposal Jinja2 template and return the HTML string."""
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
        "seo_sprint": "SEO Sprint -- Puesta a punto",
        "migration": "Supervision de migracion web",
        "market_study": "Estudio estrategico de mercado SEO",
        "consulting_retainer": "Consultoria SEO estrategica",
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
    return template.render(
        title=prop.title,
        company_name=prop.company_name or "Cliente",
        service_label=service_label,
        date_str=(prop.created_at or datetime.now(timezone.utc).replace(tzinfo=None)).strftime("%d de %B de %Y"),
        content=content,
        pricing=pricing_safe,
    )


# ── Routes ───────────────────────────────────────────────────


@router.post("/{proposal_id}/generate-pdf")
async def generate_proposal_pdf(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    """Generate a binary PDF for the proposal (application/pdf)."""
    result = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = result.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    loop = asyncio.get_event_loop()
    pdf_bytes = await loop.run_in_executor(None, _build_pdf, prop)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="propuesta-{proposal_id}.pdf"'},
    )


@router.get("/{proposal_id}/pdf")
async def get_proposal_pdf(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("proposals")),
):
    """Render proposal as print-ready HTML. Uses standard Bearer auth."""
    html_content = await _build_proposal_html(proposal_id, db)
    return Response(content=html_content, media_type="text/html")


# ── Send by email ───────────────────────────────────────────


@router.post("/{proposal_id}/draft-email")
async def draft_proposal_email(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("proposals")),
):
    """Generate an AI-written email draft for sending a proposal."""
    from backend.services.email_drafter import draft_email

    r = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = r.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    # Build context for the email drafter
    pricing = prop.pricing_options or []
    recommended = next((p for p in pricing if p.get("recommended")), pricing[0] if pricing else None)
    price_str = f"{recommended['price']:,.0f} EUR" if recommended and recommended.get("price") else None

    context_parts = []
    if prop.situation:
        context_parts.append(f"Situacion actual: {prop.situation}")
    if prop.opportunity:
        context_parts.append(f"Oportunidad: {prop.opportunity}")
    if prop.generated_content and isinstance(prop.generated_content, dict):
        exec_summary = prop.generated_content.get("executive_summary")
        if exec_summary:
            context_parts.append(f"Resumen ejecutivo de la propuesta: {exec_summary}")
    if price_str:
        context_parts.append(f"Inversion propuesta: {price_str}")
    if prop.valid_until:
        context_parts.append(f"Valida hasta: {prop.valid_until.strftime('%d/%m/%Y')}")

    purpose = f"enviar propuesta '{prop.title}' a {prop.company_name}"

    try:
        result = await draft_email(
            client_name=prop.company_name or "el cliente",
            contact_name=prop.contact_name,
            purpose=purpose,
            project_context="\n".join(context_parts) if context_parts else None,
        )
        return result
    except Exception as e:
        logger.error("Error drafting proposal email: %s", e)
        raise HTTPException(status_code=502, detail="Error generando el borrador con IA")


class ProposalEmailRequest(BaseModel):
    to_email: str
    message: Optional[str] = None


@router.post("/{proposal_id}/send-email")
async def send_proposal_email(
    proposal_id: int,
    body: ProposalEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals", write=True)),
):
    """Send a proposal by email."""
    from backend.services.email_service import send_email
    from backend.config import settings

    r = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    prop = r.scalar_one_or_none()
    if not prop:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")

    # Check SMTP configured
    if not settings.SMTP_HOST:
        raise HTTPException(
            status_code=400,
            detail="SMTP no configurado. Anade SMTP_HOST, SMTP_USER, SMTP_PASSWORD y SMTP_FROM a las variables de entorno."
        )

    company = prop.company_name or (prop.client.name if prop.client else "tu empresa")
    subject = f"Propuesta de servicios -- {company}"

    custom_msg = f"<p>{body.message}</p>" if body.message else ""
    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #1a1a1a;">Propuesta de servicios para {company}</h2>
    {custom_msg}
    <p>Adjunto encontraras nuestra propuesta detallada.</p>
    <p>Quedo a tu disposicion para cualquier consulta.</p>
    <br>
    <p style="color: #666;">-- {current_user.full_name}<br>Magnify Agency</p>
    </body></html>
    """
    text = f"Propuesta de servicios para {company}\n\n{body.message or ''}\n\nAdjunto encontraras nuestra propuesta.\n\n-- {current_user.full_name}"

    # Try to generate PDF attachment
    pdf_bytes = None
    try:
        loop = asyncio.get_event_loop()
        pdf_bytes = await loop.run_in_executor(None, _build_pdf, prop)
    except Exception:
        pdf_bytes = None

    ok = await send_email(
        to=body.to_email,
        subject=subject,
        body_html=html,
        body_text=text,
        attachment_bytes=pdf_bytes,
        attachment_name=f"propuesta-{company.lower().replace(' ', '-')}.pdf",
    )

    if not ok:
        raise HTTPException(status_code=500, detail="Error al enviar el email. Verifica la configuracion SMTP.")

    # Mark as sent
    prop.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    prop.status = ProposalStatus.sent
    await db.commit()

    return {"ok": True, "to": body.to_email}
