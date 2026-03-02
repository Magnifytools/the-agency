"""Service for generating client monthly SEO reports with real Engine data + Agency hours."""

from __future__ import annotations

import calendar
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    Client, GeneratedReport, ReportType,
    Task, TaskStatus, TimeEntry, CommunicationLog,
)
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)


async def generate_client_monthly_report(
    db: AsyncSession,
    client_id: int,
    year: int,
    month: int,
    user_id: int,
) -> GeneratedReport:
    """Generate a monthly SEO report for a client using Engine data + Agency hours."""
    # 1. Load client
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise ValueError(f"Client {client_id} not found")
    if not client.engine_project_id:
        raise ValueError(f"Client {client_id} has no linked Engine project")

    # 2. Date range
    last_day = calendar.monthrange(year, month)[1]
    from_date = f"{year}-{month:02d}-01"
    to_date = f"{year}-{month:02d}-{last_day}"
    period_start = datetime(year, month, 1)
    period_end = datetime(year, month, last_day, 23, 59, 59)

    # 3. Fetch report data from Engine
    engine_data = {}
    base = (settings.ENGINE_API_URL or "").rstrip("/")
    if base and settings.ENGINE_SERVICE_KEY:
        headers = {"X-Service-Key": settings.ENGINE_SERVICE_KEY}
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.get(
                    f"{base}/api/integration/projects/{client.engine_project_id}/report-data",
                    headers=headers,
                    params={"from_date": from_date, "to_date": to_date},
                )
                if resp.status_code == 200:
                    engine_data = resp.json()
                else:
                    logger.warning("Engine report-data fetch failed: HTTP %d", resp.status_code)
        except Exception:
            logger.exception("Error fetching Engine report-data for client %d", client_id)

    # 4. Query Agency data: time entries, tasks, communications
    time_result = await db.execute(
        select(
            TimeEntry.user_id,
            func.sum(TimeEntry.minutes).label("total_minutes"),
        )
        .join(Task, TimeEntry.task_id == Task.id)
        .where(
            Task.client_id == client_id,
            TimeEntry.date >= from_date,
            TimeEntry.date <= to_date,
        )
        .group_by(TimeEntry.user_id)
    )
    hours_by_user = {row.user_id: row.total_minutes or 0 for row in time_result.all()}
    total_minutes = sum(hours_by_user.values())

    completed_tasks_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.completed,
            Task.updated_at >= period_start,
            Task.updated_at <= period_end,
        )
    )
    completed_tasks = completed_tasks_result.scalar() or 0

    comms_result = await db.execute(
        select(func.count(CommunicationLog.id)).where(
            CommunicationLog.client_id == client_id,
            CommunicationLog.occurred_at >= from_date,
            CommunicationLog.occurred_at <= to_date,
        )
    )
    communications_count = comms_result.scalar() or 0

    # 5. Build AI prompt
    kpis = engine_data.get("kpis", {})
    month_name = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ][month - 1]

    prompt = f"""Genera un informe mensual SEO profesional para el cliente "{client.name}" correspondiente a {month_name} {year}.

DATOS SEO (de Google Search Console via Engine):
- Clicks: {kpis.get('clicks', {}).get('current', 'N/A')} (variacion: {kpis.get('clicks', {}).get('change_pct', 'N/A')}%)
- Impresiones: {kpis.get('impressions', {}).get('current', 'N/A')} (variacion: {kpis.get('impressions', {}).get('change_pct', 'N/A')}%)
- Posicion media: {kpis.get('avg_position', {}).get('current', 'N/A')}
- Paginas indexadas: {kpis.get('pages_indexed', {}).get('current', 'N/A')}

TOP KEYWORDS: {json.dumps(engine_data.get('top_keywords', [])[:5], ensure_ascii=False)}
TOP PAGINAS: {json.dumps(engine_data.get('top_pages', [])[:5], ensure_ascii=False)}

ACTUALIZACIONES DE CONTENIDO: {len(engine_data.get('content_updates', []))} paginas actualizadas
SALUD TECNICA: Tasa de indexacion {engine_data.get('technical_health', {}).get('indexation_rate', 'N/A')}
VISIBILIDAD IA: {engine_data.get('ai_visibility', {}).get('citation_count', 0)} citaciones encontradas

TRABAJO REALIZADO (de Agency):
- Horas dedicadas: {round(total_minutes / 60, 1)}h
- Tareas completadas: {completed_tasks}
- Comunicaciones: {communications_count}

Responde en JSON con esta estructura exacta:
{{
  "executive_summary": "Resumen ejecutivo de 2-3 frases",
  "performance": "Analisis del rendimiento SEO del mes",
  "highlights": "Logros y puntos destacados",
  "areas_attention": "Areas que necesitan atencion",
  "work_done": "Resumen del trabajo realizado por el equipo",
  "next_steps": "Proximos pasos recomendados",
  "kpi_table": [
    {{"metric": "Clicks", "current": 0, "previous": 0, "change_pct": 0}},
    {{"metric": "Impresiones", "current": 0, "previous": 0, "change_pct": 0}},
    {{"metric": "Posicion media", "current": 0, "previous": 0, "change_pct": 0}},
    {{"metric": "Paginas indexadas", "current": 0, "previous": null, "change_pct": null}}
  ]
}}

Escribe en espanol profesional. Se conciso pero informativo. Usa los datos reales proporcionados."""

    # 6. Call Claude API
    ai_client = get_anthropic_client()
    message = await ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system="Eres un consultor SEO senior generando informes mensuales profesionales para clientes de agencia. Responde unicamente en JSON valido.",
        messages=[{"role": "user", "content": prompt}],
    )
    ai_data = parse_claude_json(message)

    # 7. Build sections for GeneratedReport
    sections = []
    section_keys = [
        ("executive_summary", "Resumen ejecutivo"),
        ("performance", "Rendimiento SEO"),
        ("highlights", "Puntos destacados"),
        ("areas_attention", "Areas de atencion"),
        ("work_done", "Trabajo realizado"),
        ("next_steps", "Proximos pasos"),
    ]
    for key, title in section_keys:
        if ai_data.get(key):
            sections.append({"title": title, "content": ai_data[key]})

    content = json.dumps({
        "sections": sections,
        "summary": ai_data.get("executive_summary", ""),
        "kpi_table": ai_data.get("kpi_table", []),
        "engine_data": {
            "kpis": kpis,
            "top_keywords": engine_data.get("top_keywords", [])[:10],
            "top_pages": engine_data.get("top_pages", [])[:10],
        },
        "agency_data": {
            "total_hours": round(total_minutes / 60, 1),
            "completed_tasks": completed_tasks,
            "communications": communications_count,
        },
    }, ensure_ascii=False)

    # 8. Save report
    report = GeneratedReport(
        report_type=ReportType.client_monthly,
        title=f"Informe mensual SEO — {client.name} — {month_name} {year}",
        generated_at=datetime.now(timezone.utc),
        period_start=period_start,
        period_end=period_end,
        content=content,
        user_id=user_id,
        client_id=client_id,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return report
