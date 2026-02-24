from __future__ import annotations
from typing import Optional
"""
PM Insights Generator Service

Analyzes current state of clients, projects, tasks and communications
to generate actionable insights for the PM.
"""

from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client, Task, Project, CommunicationLog, PMInsight, AlertSettings,
    TaskStatus, ClientStatus, ProjectStatus,
    InsightType, InsightPriority, InsightStatus,
)


class AlertThresholds:
    """Default alert thresholds, can be overridden by user settings."""
    def __init__(
        self,
        days_without_activity: int = 14,
        days_before_deadline: int = 3,
        days_without_contact: int = 10,
        max_tasks_per_week: int = 15,
    ):
        self.days_without_activity = days_without_activity
        self.days_before_deadline = days_before_deadline
        self.days_without_contact = days_without_contact
        self.max_tasks_per_week = max_tasks_per_week


async def get_user_thresholds(db: AsyncSession, user_id: Optional[int]) -> AlertThresholds:
    """Get alert thresholds for user, or defaults if not set."""
    if user_id:
        result = await db.execute(
            select(AlertSettings).where(AlertSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            return AlertThresholds(
                days_without_activity=settings.days_without_activity,
                days_before_deadline=settings.days_before_deadline,
                days_without_contact=settings.days_without_contact,
                max_tasks_per_week=settings.max_tasks_per_week,
            )
    return AlertThresholds()


async def generate_insights(db: AsyncSession, user_id: Optional[int] = None) -> list[PMInsight]:
    """
    Generate insights based on current state.
    Returns list of newly created insights.
    Uses user's alert settings for thresholds.
    """
    now = datetime.utcnow()
    new_insights = []

    # Get user's thresholds
    thresholds = await get_user_thresholds(db, user_id)

    # 1. Overdue tasks (due_date < today and not completed)
    overdue_tasks = await db.execute(
        select(Task)
        .where(Task.due_date < now)
        .where(Task.status != TaskStatus.completed)
        .order_by(Task.due_date.asc())
    )
    overdue_list = list(overdue_tasks.scalars().all())

    if overdue_list:
        # Group by client
        by_client: dict[int, list] = {}
        for t in overdue_list:
            by_client.setdefault(t.client_id, []).append(t)

        for client_id, tasks in by_client.items():
            client = tasks[0].client
            days_overdue = (now - min(t.due_date for t in tasks)).days

            insight = PMInsight(
                insight_type=InsightType.overdue,
                priority=InsightPriority.high,
                title=f"🔴 {len(tasks)} tareas vencidas con {client.name}",
                description=f"Hay {len(tasks)} tareas vencidas desde hace {days_overdue} días. La más antigua: '{tasks[0].title}'.",
                suggested_action="Revisar las tareas vencidas y actualizar fechas o marcar como completadas.",
                status=InsightStatus.active,
                generated_at=now,
                expires_at=now + timedelta(days=7),
                user_id=user_id,
                client_id=client_id,
            )
            new_insights.append(insight)

    # 2. Tasks due soon (based on user threshold)
    soon_start = now
    soon_end = now + timedelta(days=thresholds.days_before_deadline)
    upcoming_tasks = await db.execute(
        select(Task)
        .where(Task.due_date >= soon_start)
        .where(Task.due_date <= soon_end)
        .where(Task.status != TaskStatus.completed)
        .order_by(Task.due_date.asc())
    )
    upcoming_list = list(upcoming_tasks.scalars().all())

    for task in upcoming_list[:5]:  # Limit to 5
        days_until = (task.due_date - now).days
        day_text = "hoy" if days_until == 0 else f"en {days_until} días"

        insight = PMInsight(
            insight_type=InsightType.deadline,
            priority=InsightPriority.medium if days_until > 1 else InsightPriority.high,
            title=f"⏰ '{task.title}' vence {day_text}",
            description=f"Tarea de {task.client.name} vence el {task.due_date.strftime('%d/%m')}.",
            suggested_action="Asegúrate de completar esta tarea a tiempo.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=task.due_date + timedelta(days=1),
            user_id=user_id,
            client_id=task.client_id,
            task_id=task.id,
        )
        new_insights.append(insight)

    # 3. Stalled clients (no task activity based on user threshold)
    threshold = now - timedelta(days=thresholds.days_without_activity)
    active_clients = await db.execute(
        select(Client).where(Client.status == ClientStatus.active)
    )

    for client in active_clients.scalars().all():
        # Check last task update
        last_task = await db.execute(
            select(Task)
            .where(Task.client_id == client.id)
            .order_by(Task.updated_at.desc())
            .limit(1)
        )
        last = last_task.scalar_one_or_none()

        if last and last.updated_at < threshold:
            days_inactive = (now - last.updated_at).days
            insight = PMInsight(
                insight_type=InsightType.stalled,
                priority=InsightPriority.medium,
                title=f"⚠️ {client.name} sin actividad",
                description=f"Este cliente no tiene movimiento en tareas desde hace {days_inactive} días.",
                suggested_action="Revisar si hay tareas pendientes o contactar al cliente.",
                status=InsightStatus.active,
                generated_at=now,
                expires_at=now + timedelta(days=7),
                user_id=user_id,
                client_id=client.id,
            )
            new_insights.append(insight)

    # 4. Pending followups from communications
    pending_followups = await db.execute(
        select(CommunicationLog)
        .where(CommunicationLog.requires_followup.is_(True))
        .where(CommunicationLog.followup_date <= now + timedelta(days=2))
        .order_by(CommunicationLog.followup_date.asc())
    )

    for comm in pending_followups.scalars().all():
        is_overdue = comm.followup_date and comm.followup_date < now

        insight = PMInsight(
            insight_type=InsightType.followup,
            priority=InsightPriority.high if is_overdue else InsightPriority.medium,
            title=f"📞 Seguimiento pendiente: {comm.client.name}",
            description=f"Comunicación del {comm.occurred_at.strftime('%d/%m')}: {comm.summary[:100]}...",
            suggested_action=comm.followup_notes or "Contactar al cliente para seguimiento.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=3),
            user_id=user_id,
            client_id=comm.client_id,
        )
        new_insights.append(insight)

    # 5. Workload analysis (tasks assigned this week)
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=7)

    this_week_tasks = await db.execute(
        select(func.count(Task.id))
        .where(Task.due_date >= week_start)
        .where(Task.due_date < week_end)
        .where(Task.status != TaskStatus.completed)
    )
    task_count = this_week_tasks.scalar() or 0

    warning_threshold = thresholds.max_tasks_per_week * 0.7  # Warn at 70%
    if task_count > warning_threshold:
        insight = PMInsight(
            insight_type=InsightType.workload,
            priority=InsightPriority.low if task_count <= thresholds.max_tasks_per_week else InsightPriority.medium,
            title=f"📊 Carga de trabajo: {task_count} tareas esta semana",
            description=f"Tienes {task_count} tareas pendientes para esta semana.",
            suggested_action="Considera priorizar o delegar algunas tareas si es necesario.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=week_end,
            user_id=user_id,
        )
        new_insights.append(insight)

    # 6. Quality Assurance: Tasks without estimation or assignees
    active_tasks_no_estimate = await db.execute(
        select(Task)
        .where(Task.status == TaskStatus.pending)
        .where(Task.estimated_minutes == None)
        .limit(20)
    )
    no_estimate_list = list(active_tasks_no_estimate.scalars().all())

    active_tasks_unassigned = await db.execute(
        select(Task)
        .where(Task.status == TaskStatus.pending)
        .where(Task.assigned_to == None)
        .limit(20)
    )
    unassigned_list = list(active_tasks_unassigned.scalars().all())

    active_tasks_no_date = await db.execute(
        select(Task)
        .where(Task.status == TaskStatus.pending)
        .where(Task.due_date == None)
        .limit(20)
    )
    no_date_list = list(active_tasks_no_date.scalars().all())

    if no_estimate_list:
        insight = PMInsight(
            insight_type=InsightType.quality,
            priority=InsightPriority.medium,
            title=f"⚠️ {len(no_estimate_list)} tareas sin tiempo estimado",
            description=f"Hay {len(no_estimate_list)} tareas activas sin estimación. Esto impide medir la rentabilidad real. Ej: '{no_estimate_list[0].title}'",
            suggested_action="Usa los filtros de Calidad (QA) para encontrar estas tareas y añadirles un estimado.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=2),
            user_id=user_id,
        )
        new_insights.append(insight)

    if unassigned_list:
        insight = PMInsight(
            insight_type=InsightType.quality,
            priority=InsightPriority.high,
            title=f"🚨 {len(unassigned_list)} tareas sin responsable",
            description=f"Hay {len(unassigned_list)} tareas en tu lista de trabajo sin responsable asignado. Ej: '{unassigned_list[0].title}'",
            suggested_action="Asigna estas tareas a un miembro del equipo para asegurar que se completen.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=2),
            user_id=user_id,
        )
        new_insights.append(insight)

    if no_date_list:
        insight = PMInsight(
            insight_type=InsightType.quality,
            priority=InsightPriority.medium,
            title=f"📅 {len(no_date_list)} tareas sin fecha límite",
            description=f"Hay {len(no_date_list)} tareas activas sin fecha límite configurada. Ej: '{no_date_list[0].title}'",
            suggested_action="Agrega fechas límite para llevar un control estricto del calendario mensual.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=2),
            user_id=user_id,
        )
        new_insights.append(insight)

    # Save all new insights
    for insight in new_insights:
        db.add(insight)

    await db.commit()

    # Refresh to get IDs
    for insight in new_insights:
        await db.refresh(insight)

    return new_insights


async def get_daily_briefing(db: AsyncSession, user_id: Optional[int] = None) -> dict:
    """
    Generate a daily briefing summary.
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Tasks due today
    today_tasks = await db.execute(
        select(Task)
        .where(Task.due_date >= today_start)
        .where(Task.due_date < today_end)
        .where(Task.status != TaskStatus.completed)
        .order_by(Task.due_date.asc())
    )
    priorities = [
        {
            "id": t.id,
            "title": t.title,
            "client": t.client.name if t.client else None,
            "due": t.due_date.isoformat() if t.due_date else None,
        }
        for t in today_tasks.scalars().all()
    ]

    # Overdue tasks
    overdue_tasks = await db.execute(
        select(Task)
        .where(Task.due_date < today_start)
        .where(Task.status != TaskStatus.completed)
        .limit(5)
    )
    alerts = [
        {
            "id": t.id,
            "title": t.title,
            "client": t.client.name if t.client else None,
            "days_overdue": (now - t.due_date).days,
        }
        for t in overdue_tasks.scalars().all()
    ]

    # Pending followups
    pending_comms = await db.execute(
        select(CommunicationLog)
        .where(CommunicationLog.requires_followup.is_(True))
        .where(CommunicationLog.followup_date <= today_end)
        .limit(5)
    )
    followups = [
        {
            "client": c.client.name if c.client else None,
            "subject": c.subject or c.summary[:50],
            "followup_date": c.followup_date.isoformat() if c.followup_date else None,
        }
        for c in pending_comms.scalars().all()
    ]

    # Generate greeting based on time
    hour = now.hour
    if hour < 12:
        greeting = "Buenos días 👋"
    elif hour < 18:
        greeting = "Buenas tardes 👋"
    else:
        greeting = "Buenas noches 👋"

    # Simple suggestion based on state
    suggestion = None
    if len(alerts) > 3:
        suggestion = "Tienes varias tareas vencidas. Considera dedicar tiempo a ponerte al día."
    elif len(priorities) == 0 and len(alerts) == 0:
        suggestion = "¡Buen trabajo! No tienes urgencias pendientes. Aprovecha para planificar."
    elif len(followups) > 0:
        suggestion = "Recuerda hacer seguimiento de tus comunicaciones pendientes."

    return {
        "date": now.strftime("%Y-%m-%d"),
        "greeting": greeting,
        "priorities": priorities,
        "alerts": alerts,
        "followups": followups,
        "suggestion": suggestion,
    }
