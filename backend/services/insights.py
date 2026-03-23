from __future__ import annotations
from typing import Optional
"""
PM Insights Generator Service

Analyzes current state of clients, projects, tasks and communications
to generate actionable insights for the PM.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client, Task, Project, CommunicationLog, PMInsight, AlertSettings, Income,
    TaskStatus, ClientStatus, ProjectStatus,
    InsightType, InsightPriority, InsightStatus,
)
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)


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


async def _enhance_insights_with_ai(
    insights: list[PMInsight],
    user_id: Optional[int],
) -> Optional[PMInsight]:
    """Use Claude to enhance suggested_action on each insight and optionally
    return a strategic ``suggestion`` insight.

    On any failure the original insights are left untouched and ``None`` is
    returned so the caller can gracefully degrade.
    """
    if not insights:
        return None

    try:
        client = get_anthropic_client()
    except ValueError:
        logger.debug("Anthropic client not configured; skipping AI enhancement")
        return None

    serialized = []
    for i, ins in enumerate(insights):
        serialized.append({
            "index": i,
            "type": ins.insight_type.value,
            "priority": ins.priority.value,
            "title": ins.title,
            "description": ins.description,
            "suggested_action": ins.suggested_action,
        })

    prompt = (
        "Eres un PM senior experto en gestión de agencias de marketing digital.\n"
        "Te paso una lista de insights detectados automáticamente. Para cada uno:\n"
        "1. Mejora el campo suggested_action con una recomendación concreta, "
        "específica y accionable (1-2 oraciones en español).\n"
        "2. Opcionalmente genera UNA recomendación estratégica general que "
        "conecte los insights entre sí.\n\n"
        "Responde SOLO con JSON válido con este esquema:\n"
        "{\n"
        '  "enhanced_actions": { "<index>": "nueva suggested_action", ... },\n'
        '  "overall_suggestion": "texto estratégico o null"\n'
        "}\n\n"
        f"Insights:\n{serialized}"
    )

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        data = parse_claude_json(message)
    except Exception:
        logger.warning("AI enhancement failed; keeping original insights", exc_info=True)
        return None

    # Apply enhanced actions in-place
    enhanced = data.get("enhanced_actions", {})
    for idx_str, action in enhanced.items():
        idx = int(idx_str)
        if 0 <= idx < len(insights) and isinstance(action, str) and action.strip():
            insights[idx].suggested_action = action.strip()

    # Build optional strategic suggestion insight
    overall = data.get("overall_suggestion")
    if overall and isinstance(overall, str) and overall.strip():
        now = datetime.utcnow()
        return PMInsight(
            insight_type=InsightType.suggestion,
            priority=InsightPriority.low,
            title="💡 Recomendación estratégica del día",
            description=overall.strip(),
            suggested_action=None,
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=1),
            user_id=user_id,
        )
    return None


async def _generate_ai_briefing_suggestion(
    priorities: list[dict],
    alerts: list[dict],
    followups: list[dict],
) -> Optional[str]:
    """Ask Claude for a contextual daily briefing suggestion.

    Returns the suggestion text, or ``None`` on any failure so the caller
    can fall back to the rule-based suggestion.
    """
    try:
        client = get_anthropic_client()
    except ValueError:
        return None

    context = {
        "tasks_today": len(priorities),
        "overdue": len(alerts),
        "followups": len(followups),
        "details": {
            "priorities": priorities[:5],
            "alerts": alerts[:5],
            "followups": followups[:5],
        },
    }

    prompt = (
        "Eres un PM senior. Basándote en el contexto del día de un gestor de "
        "agencia, genera UNA sugerencia breve y accionable en español "
        "(máximo 2 oraciones) para ayudarle a priorizar su jornada.\n\n"
        "Responde SOLO con JSON válido: {\"suggestion\": \"texto\"}\n\n"
        f"Contexto:\n{context}"
    )

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        data = parse_claude_json(message)
    except Exception:
        logger.warning("AI briefing suggestion failed; using fallback", exc_info=True)
        return None

    suggestion = data.get("suggestion")
    if isinstance(suggestion, str) and suggestion.strip():
        return suggestion.strip()
    return None


async def _generate_overdue_income_insights(
    db: AsyncSession, user_id: Optional[int], now: datetime
) -> list[PMInsight]:
    """Generate insights for pending income entries overdue >15 days."""
    today = now.date()

    result = await db.execute(
        select(
            Income.client_id,
            Client.name.label("client_name"),
            func.sum(Income.amount).label("total_amount"),
            func.min(Income.date).label("oldest_date"),
            func.min(Income.due_date).label("oldest_due_date"),
        )
        .join(Client, Income.client_id == Client.id, isouter=True)
        .where(Income.status == "pendiente")
        .group_by(Income.client_id, Client.name)
    )

    insights = []
    for row in result.all():
        ref_date = row.oldest_due_date if row.oldest_due_date else row.oldest_date
        if ref_date is None:
            continue
        days_pending = (today - ref_date).days
        if days_pending <= 15:
            continue

        client_name = row.client_name or f"Cliente #{row.client_id}"
        insight = PMInsight(
            insight_type=InsightType.overdue,
            priority=InsightPriority.high,
            title=f"💰 {int(row.total_amount or 0)}€ pendiente de cobro con {client_name}",
            description=f"Llevan {days_pending} días sin cobrar.",
            suggested_action="Enviar recordatorio de pago al cliente.",
            status=InsightStatus.active,
            generated_at=now,
            expires_at=now + timedelta(days=7),
            user_id=user_id,
            client_id=row.client_id,
        )
        insights.append(insight)

    return insights


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
    overdue_q = (
        select(Task)
        .where(Task.due_date < now)
        .where(Task.status != TaskStatus.completed)
    )
    if user_id is not None:
        overdue_q = overdue_q.where(Task.assigned_to == user_id)
    overdue_tasks = await db.execute(overdue_q.order_by(Task.due_date.asc()))
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
    upcoming_q = (
        select(Task)
        .where(Task.due_date >= soon_start)
        .where(Task.due_date <= soon_end)
        .where(Task.status != TaskStatus.completed)
    )
    if user_id is not None:
        upcoming_q = upcoming_q.where(Task.assigned_to == user_id)
    upcoming_tasks = await db.execute(upcoming_q.order_by(Task.due_date.asc()))
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

    # Overdue income alerts (>15 days pending)
    overdue_income = await _generate_overdue_income_insights(db, user_id, now)
    new_insights.extend(overdue_income)

    # Enhance insights with AI (best-effort; originals kept on failure)
    ai_suggestion = await _enhance_insights_with_ai(new_insights, user_id)
    if ai_suggestion is not None:
        new_insights.append(ai_suggestion)

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
    now = datetime.utcnow()  # naive UTC — matches DB DateTime columns (no tz)
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

    # Try AI-powered suggestion first, fall back to rule-based
    suggestion = await _generate_ai_briefing_suggestion(priorities, alerts, followups)

    if suggestion is None:
        # Rule-based fallback
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
