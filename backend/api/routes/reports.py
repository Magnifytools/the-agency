from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from jinja2 import Environment, BaseLoader
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import GeneratedReport, User, UserRole
from backend.schemas.report import (
    ReportRequest, ReportResponse, ReportSection, ReportNarrativeRequest,
)
from backend.services.reports import generate_report
from backend.services.report_narrator import generate_report_narrative
from backend.api.deps import get_current_user, require_module
from backend.core.rate_limiter import ai_limiter

router = APIRouter(prefix="/api/reports", tags=["reports"])
logger = logging.getLogger(__name__)


def _to_response(report: GeneratedReport) -> ReportResponse:
    try:
        content = json.loads(report.content) if report.content else {}
    except (json.JSONDecodeError, TypeError):
        content = {}
    return ReportResponse(
        id=report.id,
        type=report.report_type.value,
        title=report.title,
        generated_at=report.generated_at.isoformat(),
        period_start=report.period_start.isoformat() if report.period_start else None,
        period_end=report.period_end.isoformat() if report.period_end else None,
        client_name=report.client.name if report.client else None,
        project_name=report.project.name if report.project else None,
        sections=[ReportSection(**s) for s in content.get("sections", [])],
        summary=content.get("summary", ""),
        audience=report.audience.value if report.audience else None,
    )


@router.post("/generate", response_model=ReportResponse)
async def create_report(
    request: ReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports", write=True)),
):
    """Generate a new report."""
    try:
        report = await generate_report(
            db,
            report_type=request.type.value,
            user_id=current_user.id,
            client_id=request.client_id,
            project_id=request.project_id,
            period=request.period.value,
            audience=request.audience,
        )
        return _to_response(report)
    except ValueError:
        raise HTTPException(status_code=400, detail="No se pudo generar el reporte con esos datos")


@router.get("", response_model=list[ReportResponse])
async def list_reports(
    limit: int = 20,
    client_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """List recently generated reports, optionally filtered by client."""
    query = select(GeneratedReport)
    # F-07: members only see their own reports
    if current_user.role != UserRole.admin:
        query = query.where(GeneratedReport.user_id == current_user.id)
    if client_id is not None:
        query = query.where(GeneratedReport.client_id == client_id)
    query = query.order_by(GeneratedReport.generated_at.desc()).limit(limit)
    result = await db.execute(query)
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Get a specific report by ID."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    # F-07: members can only see their own reports
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    return _to_response(report)


@router.post("/{report_id}/ai-narrative")
async def generate_narrative(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Generate an AI narrative version of an existing report."""
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)

    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    content = json.loads(report.content)
    sections = content.get("sections", [])
    summary = content.get("summary", "")

    try:
        narrative = await generate_report_narrative(
            report_title=report.title,
            sections=sections,
            summary=summary,
            client_name=report.client.name if report.client else None,
            project_name=report.project.name if report.project else None,
            audience=report.audience.value if report.audience else None,
        )
    except ValueError:
        raise HTTPException(status_code=502, detail="No se pudo generar la narrativa del reporte")
    except Exception:
        logger.exception("Unexpected error generating report narrative for report_id=%s", report_id)
        raise HTTPException(status_code=502, detail="Error generando narrativa")

    return narrative


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports", write=True)),
):
    """Delete a report."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    # F-07: members can only delete their own reports
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    await db.delete(report)
    await db.commit()

    return {"ok": True}


# ---------------------------------------------------------------------------
# PDF Export (HTML-based, browser print)
# ---------------------------------------------------------------------------

REPORT_PDF_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  @page { size: A4; margin: 20mm 18mm 20mm 18mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; color: #1a1a1a; line-height: 1.6; font-size: 14px; }
  .cover { page-break-after: always; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 90vh; text-align: center; }
  .cover-logo { font-size: 42px; font-weight: 800; letter-spacing: -1px; color: #111; margin-bottom: 8px; }
  .cover-logo span { color: #6366f1; }
  .cover-subtitle { font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 48px; }
  .cover-title { font-size: 28px; font-weight: 700; color: #111; margin-bottom: 12px; max-width: 500px; }
  .cover-meta { font-size: 14px; color: #666; margin-bottom: 6px; }
  .cover-badge { display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-top: 20px; }
  .badge-executive { background: #ede9fe; color: #6d28d9; }
  .badge-marketing { background: #dbeafe; color: #2563eb; }
  .badge-operational { background: #d1fae5; color: #059669; }
  .content { padding: 0; }
  .exec-summary { background: #f5f3ff; border-left: 4px solid #6366f1; padding: 16px 20px; margin-bottom: 28px; border-radius: 0 8px 8px 0; }
  .exec-summary h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #6366f1; margin-bottom: 6px; }
  .exec-summary p { font-size: 14px; color: #333; }
  .section { margin-bottom: 24px; }
  .section h3 { font-size: 16px; font-weight: 700; color: #111; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #e5e7eb; }
  .section-content { font-size: 14px; color: #333; white-space: pre-line; }
  .scqa-section { background: #fafafa; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; border: 1px solid #e5e7eb; }
  .scqa-section h3 { font-size: 15px; font-weight: 700; color: #6366f1; margin-bottom: 6px; border-bottom: none; padding-bottom: 0; }
  .scqa-section .section-content { font-size: 14px; }
  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center; font-size: 11px; color: #999; }
  .footer a { color: #6366f1; text-decoration: none; }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .cover { min-height: 100vh; }
  }
</style>
</head>
<body>
  <div class="cover">
    <div class="cover-logo">MAGNIFY<span>.</span></div>
    <div class="cover-subtitle">Digital Marketing Agency</div>
    <div class="cover-title">{{ title }}</div>
    {% if client_name %}<div class="cover-meta">Cliente: {{ client_name }}</div>{% endif %}
    {% if project_name %}<div class="cover-meta">Proyecto: {{ project_name }}</div>{% endif %}
    <div class="cover-meta">{{ date }}</div>
    {% if period_start and period_end %}
    <div class="cover-meta">Per&iacute;odo: {{ period_start }} &ndash; {{ period_end }}</div>
    {% endif %}
    {% if audience %}
    <div class="cover-badge badge-{{ audience }}">
      {{ audience_label }}
    </div>
    {% endif %}
  </div>

  <div class="content">
    {% if executive_summary %}
    <div class="exec-summary">
      <h3>Resumen Ejecutivo</h3>
      <p>{{ executive_summary }}</p>
    </div>
    {% endif %}

    {% if scqa_sections %}
      {% for s in scqa_sections %}
      <div class="scqa-section">
        <h3>{{ s.title }}</h3>
        <div class="section-content">{{ s.content }}</div>
      </div>
      {% endfor %}
    {% else %}
      {% for s in sections %}
      <div class="section">
        <h3>{{ s.title }}</h3>
        <div class="section-content">{{ s.content }}</div>
      </div>
      {% endfor %}
    {% endif %}
  </div>

  <div class="footer">
    <a href="https://magnify.ing">magnify.ing</a> &middot; Generado por The Agency &middot; {{ date }}
  </div>
</body>
</html>
"""

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)
_report_template = _jinja_env.from_string(REPORT_PDF_HTML_TEMPLATE)

AUDIENCE_LABELS = {
    "executive": "Ejecutivo",
    "marketing": "Marketing",
    "operational": "Operativo",
}


def _render_report_html(
    report: GeneratedReport,
    executive_summary: str = "",
    scqa_sections: list[dict] | None = None,
) -> str:
    content = json.loads(report.content)
    sections = content.get("sections", [])
    summary = content.get("summary", "")
    audience = report.audience.value if report.audience else None

    return _report_template.render(
        title=report.title,
        client_name=report.client.name if report.client else None,
        project_name=report.project.name if report.project else None,
        date=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        period_start=report.period_start.strftime("%d/%m/%Y") if report.period_start else None,
        period_end=report.period_end.strftime("%d/%m/%Y") if report.period_end else None,
        audience=audience,
        audience_label=AUDIENCE_LABELS.get(audience, "") if audience else "",
        executive_summary=executive_summary or summary,
        sections=sections,
        scqa_sections=scqa_sections or [],
    )


@router.get("/{report_id}/pdf")
async def get_report_pdf(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Render structured report as printable HTML (browser Ctrl+P for PDF)."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    html = _render_report_html(report)
    return Response(content=html, media_type="text/html")


@router.post("/{report_id}/pdf")
async def get_report_narrative_pdf(
    report_id: int,
    body: ReportNarrativeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Render narrative (SCQA) report as printable HTML."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    html = _render_report_html(
        report,
        executive_summary=body.executive_summary,
        scqa_sections=body.scqa_sections,
    )
    return Response(content=html, media_type="text/html")


@router.get("/{report_id}/download")
async def download_report_pdf(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Download report as server-generated PDF (fpdf2)."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    import asyncio
    loop = asyncio.get_event_loop()
    pdf_bytes = await loop.run_in_executor(None, _build_report_pdf, report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{report_id}.pdf"'},
    )


def _safe_r(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _build_report_pdf(report: "GeneratedReport") -> bytes:
    from fpdf import FPDF

    content = json.loads(report.content) if isinstance(report.content, str) else (report.content or {})
    sections = content.get("sections", [])
    summary = content.get("summary", "")
    audience = report.audience.value if report.audience else None

    AUDIENCE_LABEL = {"executive": "Ejecutivo", "marketing": "Marketing", "operational": "Operativo"}

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 15, 20)

    # Cover
    pdf.add_page()
    pdf.set_y(70)
    pdf.set_font("Helvetica", "B", 32)
    pdf.cell(0, 12, "MAGNIFY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "INFORME DE RESULTADOS", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, _safe_r(report.title or ""), align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 11)
    meta_parts = []
    if report.client:
        meta_parts.append(report.client.name)
    if report.period_start and report.period_end:
        meta_parts.append(f"{report.period_start.strftime('%d/%m/%Y')} - {report.period_end.strftime('%d/%m/%Y')}")
    if audience:
        meta_parts.append(AUDIENCE_LABEL.get(audience, audience))
    pdf.cell(0, 6, _safe_r(" | ".join(meta_parts)), align="C", new_x="LMARGIN", new_y="NEXT")

    # Content
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 5, "MAGNIFY", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(30, 30, 30)
    pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    if summary:
        pdf.set_fill_color(240, 244, 255)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe_r(str(summary)), fill=True, border=1)
        pdf.ln(4)

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        title = sec.get("title", "")
        body = sec.get("content", sec.get("body", ""))
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _safe_r(str(title)), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe_r(str(body)))
        pdf.ln(2)

    # Footer
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, _safe_r(f"magnify.ing | Generado {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"), align="C")
    pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Client Monthly Report (Engine + Agency data)
# ---------------------------------------------------------------------------

class ClientMonthlyRequest(BaseModel):
    client_id: int
    year: int
    month: int


@router.post("/generate-client-monthly", response_model=ReportResponse)
async def generate_client_monthly(
    body: ClientMonthlyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports", write=True)),
):
    """Generate a monthly SEO report for a client using Engine + Agency data."""
    if not (1 <= body.month <= 12) or not (2000 <= body.year <= 2100):
        raise HTTPException(status_code=400, detail="Mes o año inválido")

    from backend.services.monthly_report_service import generate_client_monthly_report

    try:
        report = await generate_client_monthly_report(
            db,
            client_id=body.client_id,
            year=body.year,
            month=body.month,
            user_id=current_user.id,
        )
        return _to_response(report)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Error generating client monthly report")
        raise HTTPException(status_code=502, detail="Error generando informe mensual")


MONTHLY_PDF_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
  @page { size: A4; margin: 20mm 18mm 20mm 18mm; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; color: #1a1a1a; line-height: 1.6; font-size: 14px; }
  .cover { page-break-after: always; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 90vh; text-align: center; }
  .cover-logo { font-size: 42px; font-weight: 800; letter-spacing: -1px; color: #111; margin-bottom: 8px; }
  .cover-logo span { color: #6366f1; }
  .cover-subtitle { font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 48px; }
  .cover-title { font-size: 28px; font-weight: 700; color: #111; margin-bottom: 12px; max-width: 500px; }
  .cover-meta { font-size: 14px; color: #666; margin-bottom: 6px; }
  .cover-badge { display: inline-block; padding: 4px 16px; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-top: 20px; background: #ede9fe; color: #6d28d9; }
  .content { padding: 0; }
  .kpi-table { width: 100%; border-collapse: collapse; margin-bottom: 28px; }
  .kpi-table th { text-align: left; padding: 8px 12px; background: #f5f3ff; color: #6366f1; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid #e5e7eb; }
  .kpi-table td { padding: 8px 12px; border-bottom: 1px solid #e5e7eb; font-size: 14px; }
  .kpi-table .number { text-align: right; font-variant-numeric: tabular-nums; }
  .trend-up { color: #059669; font-weight: 600; }
  .trend-down { color: #dc2626; font-weight: 600; }
  .trend-neutral { color: #6b7280; }
  .section { margin-bottom: 24px; }
  .section h3 { font-size: 16px; font-weight: 700; color: #111; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #e5e7eb; }
  .section-content { font-size: 14px; color: #333; white-space: pre-line; }
  .exec-summary { background: #f5f3ff; border-left: 4px solid #6366f1; padding: 16px 20px; margin-bottom: 28px; border-radius: 0 8px 8px 0; }
  .exec-summary h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #6366f1; margin-bottom: 6px; }
  .exec-summary p { font-size: 14px; color: #333; }
  .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center; font-size: 11px; color: #999; }
  .footer a { color: #6366f1; text-decoration: none; }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .cover { min-height: 100vh; }
  }
</style>
</head>
<body>
  <div class="cover">
    <div class="cover-logo">MAGNIFY<span>.</span></div>
    <div class="cover-subtitle">Digital Marketing Agency</div>
    <div class="cover-title">Informe Mensual SEO</div>
    <div class="cover-meta">{{ client_name }}</div>
    <div class="cover-meta">{{ period }}</div>
    <div class="cover-badge">Informe mensual</div>
  </div>

  <div class="content">
    {% if executive_summary %}
    <div class="exec-summary">
      <h3>Resumen Ejecutivo</h3>
      <p>{{ executive_summary }}</p>
    </div>
    {% endif %}

    {% if kpi_table %}
    <table class="kpi-table">
      <thead>
        <tr>
          <th>M&eacute;trica</th>
          <th class="number">Actual</th>
          <th class="number">Anterior</th>
          <th class="number">Variaci&oacute;n</th>
        </tr>
      </thead>
      <tbody>
        {% for kpi in kpi_table %}
        <tr>
          <td>{{ kpi.metric }}</td>
          <td class="number">{{ kpi.current if kpi.current is not none else '-' }}</td>
          <td class="number">{{ kpi.previous if kpi.previous is not none else '-' }}</td>
          <td class="number {% if kpi.change_pct is not none %}{% if kpi.change_pct > 0 %}trend-up{% elif kpi.change_pct < 0 %}trend-down{% else %}trend-neutral{% endif %}{% endif %}">
            {% if kpi.change_pct is not none %}{{ '+' if kpi.change_pct > 0 else '' }}{{ kpi.change_pct }}%{% else %}-{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% for s in sections %}
    <div class="section">
      <h3>{{ s.title }}</h3>
      <div class="section-content">{{ s.content }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="footer">
    <a href="https://magnify.ing">magnify.ing</a> &middot; Generado por The Agency &middot; {{ date }}
  </div>
</body>
</html>
"""

_monthly_template = _jinja_env.from_string(MONTHLY_PDF_HTML_TEMPLATE)


@router.get("/client-monthly/{report_id}/pdf")
async def get_monthly_report_pdf(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Render monthly report as printable HTML."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    content = json.loads(report.content)
    sections = content.get("sections", [])
    summary = content.get("summary", "")
    kpi_table = content.get("kpi_table", [])

    months = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    period = ""
    if report.period_start and report.period_end:
        period = f"{months[report.period_start.month - 1]} {report.period_start.year}"

    html = _monthly_template.render(
        title=report.title,
        client_name=report.client.name if report.client else "",
        period=period,
        date=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        executive_summary=summary,
        kpi_table=kpi_table,
        sections=sections,
    )
    return Response(content=html, media_type="text/html")
