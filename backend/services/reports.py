from __future__ import annotations
from typing import Optional
"""
Report Generation Service

Generates status reports for clients, projects, and weekly summaries.
"""

import json
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client, Task, Project, CommunicationLog, TimeEntry, GeneratedReport,
    TaskStatus, ClientStatus, ProjectStatus, ReportType,
)


async def generate_client_status_report(
    db: AsyncSession,
    client_id: int,
    user_id: int,
    period: str = "month",
) -> GeneratedReport:
    """Generate a status report for a specific client."""
    now = datetime.utcnow()

    # Calculate period
    if period == "week":
        period_start = now - timedelta(days=7)
    else:  # month
        period_start = now - timedelta(days=30)

    # Fetch client
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise ValueError(f"Client {client_id} not found")

    # Fetch tasks for period
    tasks_result = await db.execute(
        select(Task)
        .where(Task.client_id == client_id)
        .where(Task.updated_at >= period_start)
    )
    tasks = list(tasks_result.scalars().all())

    completed_tasks = [t for t in tasks if t.status == TaskStatus.completed]
    pending_tasks = [t for t in tasks if t.status == TaskStatus.pending]
    in_progress_tasks = [t for t in tasks if t.status == TaskStatus.in_progress]

    # Fetch time entries
    time_result = await db.execute(
        select(func.sum(TimeEntry.minutes))
        .join(Task)
        .where(Task.client_id == client_id)
        .where(TimeEntry.date >= period_start)
    )
    total_minutes = time_result.scalar() or 0
    total_hours = round(total_minutes / 60, 1)

    # Fetch communications
    comms_result = await db.execute(
        select(CommunicationLog)
        .where(CommunicationLog.client_id == client_id)
        .where(CommunicationLog.occurred_at >= period_start)
        .order_by(CommunicationLog.occurred_at.desc())
        .limit(5)
    )
    recent_comms = list(comms_result.scalars().all())

    # Fetch active projects
    projects_result = await db.execute(
        select(Project)
        .where(Project.client_id == client_id)
        .where(Project.status == ProjectStatus.active)
    )
    active_projects = list(projects_result.scalars().all())

    # Build report sections
    sections = []

    # Executive Summary
    status_emoji = "✅" if len(pending_tasks) < 3 else "⚠️" if len(pending_tasks) < 5 else "🔴"
    summary_text = f"{status_emoji} El cliente tiene {len(completed_tasks)} tareas completadas y {len(pending_tasks)} pendientes este período. "
    if total_hours > 0:
        summary_text += f"Se han dedicado {total_hours}h de trabajo. "
    if active_projects:
        summary_text += f"Hay {len(active_projects)} proyectos activos."

    sections.append({
        "title": "Resumen Ejecutivo",
        "content": summary_text,
    })

    # Progress
    progress_content = f"- Tareas completadas: {len(completed_tasks)}\n"
    progress_content += f"- Tareas en curso: {len(in_progress_tasks)}\n"
    progress_content += f"- Tareas pendientes: {len(pending_tasks)}\n"
    progress_content += f"- Horas dedicadas: {total_hours}h"
    sections.append({
        "title": "Progreso del Período",
        "content": progress_content,
    })

    # Achievements
    if completed_tasks:
        achievements = "\n".join([f"- {t.title}" for t in completed_tasks[:5]])
        sections.append({
            "title": "Logros Destacados",
            "content": achievements,
        })

    # Next Steps
    if pending_tasks or in_progress_tasks:
        next_steps = "\n".join([f"- {t.title}" for t in (in_progress_tasks + pending_tasks)[:5]])
        sections.append({
            "title": "Próximos Pasos",
            "content": next_steps,
        })

    # Communications
    if recent_comms:
        comms_content = "\n".join([
            f"- {c.occurred_at.strftime('%d/%m')}: {c.summary[:80]}..."
            for c in recent_comms
        ])
        sections.append({
            "title": "Comunicaciones Recientes",
            "content": comms_content,
        })

    # Create report
    period_name = "semana" if period == "week" else "mes"
    report = GeneratedReport(
        report_type=ReportType.client_status,
        title=f"Informe de estado - {client.name} ({period_name})",
        generated_at=now,
        period_start=period_start,
        period_end=now,
        content=json.dumps({
            "sections": sections,
            "summary": summary_text,
        }),
        user_id=user_id,
        client_id=client_id,
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    return report


async def generate_weekly_summary_report(
    db: AsyncSession,
    user_id: int,
) -> GeneratedReport:
    """Generate a weekly summary report for all clients."""
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)

    # Fetch all completed tasks this week
    tasks_result = await db.execute(
        select(Task)
        .where(Task.updated_at >= week_start)
        .where(Task.status == TaskStatus.completed)
    )
    completed_tasks = list(tasks_result.scalars().all())

    # Group by client
    by_client: dict[int, list] = {}
    for t in completed_tasks:
        by_client.setdefault(t.client_id, []).append(t)

    # Fetch time by client
    time_result = await db.execute(
        select(Task.client_id, func.sum(TimeEntry.minutes))
        .join(TimeEntry)
        .where(TimeEntry.date >= week_start)
        .group_by(Task.client_id)
    )
    time_by_client = {row[0]: row[1] for row in time_result.all()}

    # Fetch all active clients
    clients_result = await db.execute(
        select(Client).where(Client.status == ClientStatus.active)
    )
    active_clients = list(clients_result.scalars().all())

    sections = []

    # Overview
    total_completed = len(completed_tasks)
    total_hours = round(sum(time_by_client.values()) / 60, 1) if time_by_client else 0
    overview = f"Esta semana se completaron {total_completed} tareas en {len(by_client)} clientes, con un total de {total_hours}h de trabajo registradas."
    sections.append({
        "title": "Resumen General",
        "content": overview,
    })

    # Per-client summary
    client_summaries = []
    for client in active_clients:
        tasks = by_client.get(client.id, [])
        hours = round((time_by_client.get(client.id, 0) or 0) / 60, 1)
        if tasks or hours:
            client_summaries.append(f"- **{client.name}**: {len(tasks)} tareas completadas, {hours}h")

    if client_summaries:
        sections.append({
            "title": "Por Cliente",
            "content": "\n".join(client_summaries),
        })

    # Pending items
    pending_result = await db.execute(
        select(Task)
        .where(Task.status != TaskStatus.completed)
        .where(Task.due_date <= now + timedelta(days=7))
        .order_by(Task.due_date.asc())
        .limit(10)
    )
    upcoming = list(pending_result.scalars().all())

    if upcoming:
        upcoming_content = "\n".join([
            f"- {t.title} ({t.client.name if t.client else 'Sin cliente'})"
            for t in upcoming
        ])
        sections.append({
            "title": "Próximas Entregas",
            "content": upcoming_content,
        })

    report = GeneratedReport(
        report_type=ReportType.weekly_summary,
        title=f"Resumen semanal - {now.strftime('%d/%m/%Y')}",
        generated_at=now,
        period_start=week_start,
        period_end=now,
        content=json.dumps({
            "sections": sections,
            "summary": overview,
        }),
        user_id=user_id,
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    return report


async def generate_project_status_report(
    db: AsyncSession,
    project_id: int,
    user_id: int,
) -> GeneratedReport:
    """Generate a status report for a specific project."""
    now = datetime.utcnow()

    # Fetch project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError(f"Project {project_id} not found")

    # Fetch tasks
    tasks_result = await db.execute(
        select(Task).where(Task.project_id == project_id)
    )
    tasks = list(tasks_result.scalars().all())

    completed_tasks = [t for t in tasks if t.status == TaskStatus.completed]
    pending_tasks = [t for t in tasks if t.status == TaskStatus.pending]
    in_progress_tasks = [t for t in tasks if t.status == TaskStatus.in_progress]

    # Fetch time
    time_result = await db.execute(
        select(func.sum(TimeEntry.minutes))
        .join(Task)
        .where(Task.project_id == project_id)
    )
    total_minutes = time_result.scalar() or 0
    total_hours = round(total_minutes / 60, 1)

    sections = []

    # Project overview
    progress = project.progress_percent or 0
    status_emoji = "✅" if progress >= 80 else "🔄" if progress >= 40 else "🚀"
    overview = f"{status_emoji} El proyecto está al {progress}% de avance. "
    if project.target_end_date:
        days_left = (project.target_end_date - now).days
        if days_left > 0:
            overview += f"Faltan {days_left} días para la fecha objetivo."
        elif days_left == 0:
            overview += "La fecha objetivo es hoy."
        else:
            overview += f"⚠️ El proyecto está {abs(days_left)} días retrasado."

    sections.append({
        "title": "Estado del Proyecto",
        "content": overview,
    })

    # Phase summary
    if project.phases:
        phase_content = "\n".join([
            f"- {p.name}: {p.status.value}"
            for p in project.phases
        ])
        sections.append({
            "title": "Fases",
            "content": phase_content,
        })

    # Task summary
    task_summary = f"- Completadas: {len(completed_tasks)}\n"
    task_summary += f"- En curso: {len(in_progress_tasks)}\n"
    task_summary += f"- Pendientes: {len(pending_tasks)}\n"
    task_summary += f"- Horas totales: {total_hours}h"
    if project.budget_hours:
        budget_pct = round((total_hours / project.budget_hours) * 100)
        task_summary += f" ({budget_pct}% del presupuesto de {project.budget_hours}h)"
    sections.append({
        "title": "Tareas",
        "content": task_summary,
    })

    # Next steps
    if in_progress_tasks or pending_tasks:
        next_steps = "\n".join([f"- {t.title}" for t in (in_progress_tasks + pending_tasks)[:5]])
        sections.append({
            "title": "Próximos Pasos",
            "content": next_steps,
        })

    # Mock Traffic / GSC Data
    if project.gsc_url or project.ga4_property_id:
        traffic_summary = ""
        if project.gsc_url:
            traffic_summary += f"📈 **Búsquedas Orgánicas (GSC)**\n- Clics estimados: 1,452 (+12%)\n- Impresiones: 12,400\n- Posición Media: 14.5\n\n"
        if project.ga4_property_id:
            traffic_summary += f"📊 **Tráfico Web (GA4)**\n- Sesiones: 3,240 (+5%)\n- Usuarios únicos: 2,800\n- Eventos clave: 125\n"
            
        sections.append({
            "title": "Analítica y Tráfico (Demo)",
            "content": traffic_summary,
        })

    report = GeneratedReport(
        report_type=ReportType.project_status,
        title=f"Informe de proyecto - {project.name}",
        generated_at=now,
        period_start=project.start_date,
        period_end=now,
        content=json.dumps({
            "sections": sections,
            "summary": overview,
        }),
        user_id=user_id,
        project_id=project_id,
        client_id=project.client_id,
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    return report


async def generate_report(
    db: AsyncSession,
    report_type: str,
    user_id: int,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
    period: str = "month",
) -> GeneratedReport:
    """Generate a report based on type."""
    if report_type == "client_status":
        if not client_id:
            raise ValueError("client_id required for client_status report")
        return await generate_client_status_report(db, client_id, user_id, period)
    elif report_type == "weekly_summary":
        return await generate_weekly_summary_report(db, user_id)
    elif report_type == "project_status":
        if not project_id:
            raise ValueError("project_id required for project_status report")
        return await generate_project_status_report(db, project_id, user_id)
    else:
        raise ValueError(f"Unknown report type: {report_type}")
