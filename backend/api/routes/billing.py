from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Client, Task, TimeEntry, User, Income
from backend.api.deps import require_module
from backend.config import settings
from backend.services.csv_utils import build_csv_response
from backend.services.report_period import (
    MAX_REPORT_YEAR,
    MIN_REPORT_YEAR,
    month_range_naive,
    resolve_default_period,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


_MONTH_NAMES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _safe(text: str) -> str:
    """Strip characters outside latin-1 so fpdf2 (built-in fonts) won't crash."""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


def _build_billing_pdf(rows: list[dict], year: int, month: int) -> bytes:
    from fpdf import FPDF

    period_label = f"{_MONTH_NAMES_ES[month]} {year}"

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 15, 20)

    pdf.add_page()

    # ── Header ──────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "MAGNIFY", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, _safe(f"Facturacion — {period_label}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(4)
    pdf.set_draw_color(30, 30, 30)
    pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    if not rows:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 8, "Sin datos para este periodo.", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        return bytes(pdf.output())

    # ── Table header ────────────────────────────────────────
    # Columns: Cliente | Horas | Coste | Presupuesto | Facturado | Margen
    col_widths = [58, 22, 26, 28, 26, 10]  # last is spacer → remaining goes to margen
    # Recalc: total usable = 170mm (210 - 20 - 20)
    col_widths = [62, 22, 26, 26, 26, 8]
    headers = ["Cliente", "Horas", "Coste", "Presupuesto", "Facturado", "Margen"]
    final_col_widths = [62, 22, 26, 26, 22, 12]
    # Total = 62+22+26+26+22+12 = 170 ✓

    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", "B", 9)
    aligns = ["L", "R", "R", "R", "R", "R"]
    for i, h in enumerate(headers):
        pdf.cell(final_col_widths[i], 7, h, border=1, fill=True, align=aligns[i])
    pdf.ln()

    # ── Table rows ──────────────────────────────────────────
    pdf.set_font("Helvetica", "", 9)
    total_cost = 0.0
    total_budget = 0.0
    total_invoiced = 0.0
    total_margin = 0.0

    for row in rows:
        client_name = _safe(row.get("client_name", ""))
        hours = row.get("hours", 0)
        cost = float(row.get("cost", 0))
        budget = float(row.get("budget", 0))
        invoiced = float(row.get("invoiced", 0))
        margin = float(row.get("margin", 0))

        total_cost += cost
        total_budget += budget
        total_invoiced += invoiced
        total_margin += margin

        def fmt_eur(v: float) -> str:
            return f"{v:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")

        pdf.cell(final_col_widths[0], 6, client_name, border=1)
        pdf.cell(final_col_widths[1], 6, f"{hours}h", border=1, align="R")
        pdf.cell(final_col_widths[2], 6, fmt_eur(cost), border=1, align="R")
        pdf.cell(final_col_widths[3], 6, fmt_eur(budget), border=1, align="R")
        pdf.cell(final_col_widths[4], 6, fmt_eur(invoiced) if invoiced > 0 else "-", border=1, align="R")
        pdf.cell(final_col_widths[5], 6, fmt_eur(margin), border=1, align="R")
        pdf.ln()

    # ── Totals row ──────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(235, 235, 235)
    pdf.cell(final_col_widths[0], 7, "TOTAL", border=1, fill=True)
    pdf.cell(final_col_widths[1], 7, "", border=1, fill=True)
    pdf.cell(final_col_widths[2], 7, fmt_eur(total_cost), border=1, fill=True, align="R")
    pdf.cell(final_col_widths[3], 7, fmt_eur(total_budget), border=1, fill=True, align="R")
    pdf.cell(final_col_widths[4], 7, fmt_eur(total_invoiced) if total_invoiced > 0 else "-", border=1, fill=True, align="R")
    pdf.cell(final_col_widths[5], 7, fmt_eur(total_margin), border=1, fill=True, align="R")
    pdf.ln()

    # ── Footer note ─────────────────────────────────────────
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4, "Documento generado automaticamente por Magnify Agency Manager. Los margenes estimados no incluyen costes indirectos.")
    pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 4, "Magnify", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4, "david@magnify.ing  |  magnify.ing", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())


@router.get("/export")
async def export_billing(
    format: str = Query("csv", pattern="^(csv|json)$"),
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("billing")),
):
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Income.date is a Date column; convert datetime → date for correct comparison
    start_date = start.date()
    end_date = end.date()

    # Subquery: real invoiced income per client for the period (cobrado + pendiente)
    invoiced_subq = (
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(
            Income.client_id == Client.id,
            Income.date >= start_date,
            Income.date <= end_date,
        )
        .scalar_subquery()
    )

    # Aggregate time + cost per client for the month
    result = await db.execute(
        select(
            Client.id,
            Client.name,
            Client.monthly_budget,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("total_minutes"),
            func.coalesce(func.sum(TimeEntry.minutes * func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE) / 60), 0).label("total_cost"),
            invoiced_subq.label("invoiced"),
        )
        .select_from(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(Client, Task.client_id == Client.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            and_(
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= start,
                TimeEntry.date <= end,
                Client.is_internal.is_(False),
            )
        )
        .group_by(Client.id)
        .order_by(Client.name)
    )

    rows = []
    for row in result.all():
        hours = round((row.total_minutes or 0) / 60, 2)
        cost = round(row.total_cost or 0, 2)
        budget = float(row.monthly_budget or 0)
        invoiced = round(float(row.invoiced or 0), 2)
        margin = round(invoiced - cost, 2) if invoiced > 0 else round(budget - cost, 2)
        rows.append({
            "client_id": row.id,
            "client_name": row.name,
            "period": f"{y}-{m:02d}",
            "hours": hours,
            "cost": cost,
            "budget": budget,
            "invoiced": invoiced,
            "margin": margin,
        })

    if format == "json":
        return rows

    # CSV export
    header = ["client_id", "client_name", "period", "hours", "cost", "budget", "invoiced", "margin"]
    csv_rows = (
        [r["client_id"], r["client_name"], r["period"], r["hours"], r["cost"], r["budget"], r["invoiced"], r["margin"]]
        for r in rows
    )
    return build_csv_response(f"billing_{y}_{m:02d}.csv", header, csv_rows)


@router.get("/export-pdf")
async def export_billing_pdf(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("billing")),
):
    """Generate a PDF summary of billing data for the given month."""
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Income.date is a Date column; convert datetime → date for correct comparison
    start_date = start.date()
    end_date = end.date()

    # Reuse the same aggregation query as /export
    invoiced_subq = (
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(
            Income.client_id == Client.id,
            Income.date >= start_date,
            Income.date <= end_date,
        )
        .scalar_subquery()
    )

    result = await db.execute(
        select(
            Client.id,
            Client.name,
            Client.monthly_budget,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("total_minutes"),
            func.coalesce(func.sum(TimeEntry.minutes * func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE) / 60), 0).label("total_cost"),
            invoiced_subq.label("invoiced"),
        )
        .select_from(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(Client, Task.client_id == Client.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            and_(
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= start,
                TimeEntry.date <= end,
                Client.is_internal.is_(False),
            )
        )
        .group_by(Client.id)
        .order_by(Client.name)
    )

    rows = []
    for row in result.all():
        hours = round((row.total_minutes or 0) / 60, 2)
        cost = round(row.total_cost or 0, 2)
        budget = float(row.monthly_budget or 0)
        invoiced = round(float(row.invoiced or 0), 2)
        margin = round(invoiced - cost, 2) if invoiced > 0 else round(budget - cost, 2)
        rows.append({
            "client_id": row.id,
            "client_name": row.name,
            "period": f"{y}-{m:02d}",
            "hours": hours,
            "cost": cost,
            "budget": budget,
            "invoiced": invoiced,
            "margin": margin,
        })

    pdf_bytes = _build_billing_pdf(rows, y, m)
    filename = f"facturacion-{y}-{m:02d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
