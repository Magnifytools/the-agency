"""In-app notifications API endpoints."""
from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Notification, Task, TaskStatus, Lead, LeadStatus
from backend.api.deps import get_current_user
from backend.schemas.notification import NotificationResponse
from backend.services.notification_service import (
    create_notification, TASK_OVERDUE, LEAD_FOLLOWUP,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# GET / — List notifications
# ---------------------------------------------------------------------------

@router.get("")
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[NotificationResponse]:
    """List notifications for the current user."""
    try:
        q = select(Notification).where(Notification.user_id == user.id)
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return [NotificationResponse.model_validate(n) for n in result.scalars().all()]
    except Exception as e:
        logger.error("Error listing notifications for user %d: %s", user.id, e)
        return []


# ---------------------------------------------------------------------------
# GET /unread-count
# ---------------------------------------------------------------------------

@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Get unread notification count for the current user."""
    try:
        result = await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.is_read.is_(False),
            )
        )
        count = result.scalar() or 0
        return {"count": count}
    except Exception as e:
        logger.error("Error counting unread notifications for user %d: %s", user.id, e)
        return {"count": 0}


# ---------------------------------------------------------------------------
# PUT /{id}/read — Mark single as read
# ---------------------------------------------------------------------------

@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Mark a single notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# PUT /read-all — Mark all as read
# ---------------------------------------------------------------------------

@router.put("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Mark all notifications as read for the current user."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /generate-checks — Create notifications for overdue tasks & lead followups
# ---------------------------------------------------------------------------

@router.post("/generate-checks")
async def generate_notification_checks(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Generate notifications for overdue tasks and lead followups due."""
    created = 0
    today = date.today()
    now = datetime.utcnow()

    # 1. Overdue tasks assigned to this user
    try:
        overdue_result = await db.execute(
            select(Task).where(
                Task.assigned_to == user.id,
                Task.due_date < now,
                Task.status != TaskStatus.completed,
            )
        )
        for task in overdue_result.scalars().all():
            # Check if unread notification already exists for this task
            existing = await db.execute(
                select(Notification.id).where(
                    Notification.user_id == user.id,
                    Notification.entity_type == "task",
                    Notification.entity_id == task.id,
                    Notification.type == TASK_OVERDUE,
                    Notification.is_read.is_(False),
                )
            )
            if not existing.scalar_one_or_none():
                due_str = task.due_date.strftime("%d/%m/%Y") if task.due_date else "—"
                await create_notification(
                    db,
                    user_id=user.id,
                    type=TASK_OVERDUE,
                    title=f"Tarea vencida: {task.title}",
                    message=f"La tarea '{task.title}' venció el {due_str}",
                    link_url="/tasks",
                    entity_type="task",
                    entity_id=task.id,
                )
                created += 1
    except Exception as e:
        logger.error("Error checking overdue tasks: %s", e)

    # 2. Lead followups due today or past
    try:
        leads_result = await db.execute(
            select(Lead).where(
                Lead.assigned_to == user.id,
                Lead.next_followup_date <= today,
                Lead.status.notin_([LeadStatus.won, LeadStatus.lost]),
            )
        )
        for lead in leads_result.scalars().all():
            existing = await db.execute(
                select(Notification.id).where(
                    Notification.user_id == user.id,
                    Notification.entity_type == "lead",
                    Notification.entity_id == lead.id,
                    Notification.type == LEAD_FOLLOWUP,
                    Notification.is_read.is_(False),
                )
            )
            if not existing.scalar_one_or_none():
                followup_str = lead.next_followup_date.strftime("%d/%m/%Y") if lead.next_followup_date else "hoy"
                await create_notification(
                    db,
                    user_id=user.id,
                    type=LEAD_FOLLOWUP,
                    title=f"Seguimiento pendiente: {lead.company_name}",
                    message=lead.next_followup_notes or f"Seguimiento programado para {followup_str}",
                    link_url=f"/leads/{lead.id}",
                    entity_type="lead",
                    entity_id=lead.id,
                )
                created += 1
    except Exception as e:
        logger.error("Error checking lead followups: %s", e)

    if created > 0:
        await db.commit()

    return {"created": created}
