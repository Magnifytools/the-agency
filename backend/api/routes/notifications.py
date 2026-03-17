"""In-app notifications API endpoints."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Notification, Task, TaskStatus, Lead, LeadStatus, Client, ClientStatus,
    UserRole, User, DailyUpdate, TimeEntry,
)
from backend.api.deps import get_current_user
from backend.schemas.notification import NotificationResponse
from backend.services.notification_service import (
    create_notification, TASK_OVERDUE, LEAD_FOLLOWUP, BILLING_REMINDER,
    DAILY_MISSING, TIMESHEET_INCOMPLETE, CAPACITY_OVERLOAD, CLIENT_NO_HOURS,
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
    """Generate notifications for overdue tasks and lead followups due.

    Optimized: pre-loads all existing unread notifications in 1 query
    instead of checking per-item (eliminates N+1 pattern).
    """
    from datetime import timedelta

    created = 0
    today = date.today()
    now = datetime.now(timezone.utc)

    # ── Pre-load ALL unread notifications for this user (1 query) ──
    existing_result = await db.execute(
        select(Notification.type, Notification.entity_type, Notification.entity_id)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    existing_set: set[tuple[str, str, int]] = {
        (row.type, row.entity_type, row.entity_id)
        for row in existing_result.all()
    }

    def _has_existing(ntype: str, etype: str, eid: int) -> bool:
        return (ntype, etype, eid) in existing_set

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
            if not _has_existing(TASK_OVERDUE, "task", task.id):
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
            if not _has_existing(LEAD_FOLLOWUP, "lead", lead.id):
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

    # 3. Billing reminders for clients due within 3 days (admin only)
    if user.role == UserRole.admin:
        try:
            threshold = today + timedelta(days=3)
            billing_result = await db.execute(
                select(Client).where(
                    Client.status == ClientStatus.active,
                    Client.next_invoice_date.isnot(None),
                    Client.next_invoice_date <= threshold,
                )
            )
            for client in billing_result.scalars().all():
                if not _has_existing(BILLING_REMINDER, "client", client.id):
                    date_str = client.next_invoice_date.strftime("%d/%m/%Y")
                    days_left = (client.next_invoice_date - today).days
                    msg = f"Toca facturar a {client.name} el {date_str}" if days_left >= 0 else f"Factura vencida para {client.name} desde el {date_str}"
                    await create_notification(
                        db,
                        user_id=user.id,
                        type=BILLING_REMINDER,
                        title=f"Facturacion: {client.name}",
                        message=msg,
                        link_url=f"/clients/{client.id}",
                        entity_type="client",
                        entity_id=client.id,
                    )
                    created += 1
        except Exception as e:
            logger.error("Error checking billing reminders: %s", e)

    # 4. Missing dailys — admin sees who hasn't submitted in 2+ business days
    if user.role == UserRole.admin:
        try:
            two_days_ago = today - timedelta(days=2)
            # Get all active non-admin users (admins don't need to submit dailys)
            all_users_result = await db.execute(
                select(User).where(User.is_active.is_(True), User.role != UserRole.admin)
            )
            all_users = all_users_result.scalars().all()

            # Batch: get user IDs who HAVE submitted a daily in the last 2 days (1 query)
            recent_daily_result = await db.execute(
                select(DailyUpdate.user_id).where(
                    DailyUpdate.date >= two_days_ago,
                ).distinct()
            )
            users_with_daily = {row[0] for row in recent_daily_result.all()}

            for u in all_users:
                if u.id not in users_with_daily and not _has_existing(DAILY_MISSING, "user", u.id):
                    await create_notification(
                        db,
                        user_id=user.id,
                        type=DAILY_MISSING,
                        title=f"Daily pendiente: {u.full_name}",
                        message=f"{u.full_name} no ha enviado daily en los últimos 2 días",
                        link_url="/dailys",
                        entity_type="user",
                        entity_id=u.id,
                    )
                    created += 1
        except Exception as e:
            logger.error("Error checking missing dailys: %s", e)

    # 5. Incomplete timesheets — users with < 6h logged yesterday (weekday)
    if user.role == UserRole.admin:
        try:
            yesterday = today - timedelta(days=1)
            # Skip weekends
            if yesterday.weekday() < 5:
                all_users_result = await db.execute(
                    select(User).where(User.is_active.is_(True), User.role != UserRole.admin)
                )
                all_users = all_users_result.scalars().all()

                # Batch: get hours per user for yesterday (1 query)
                hours_by_user_result = await db.execute(
                    select(
                        TimeEntry.user_id,
                        func.coalesce(func.sum(TimeEntry.minutes), 0).label("total"),
                    ).where(
                        func.date(TimeEntry.date) == yesterday,
                    ).group_by(TimeEntry.user_id)
                )
                hours_map = {row.user_id: row.total for row in hours_by_user_result.all()}

                for u in all_users:
                    total_minutes = hours_map.get(u.id, 0)
                    if total_minutes < 360 and not _has_existing(TIMESHEET_INCOMPLETE, "user", u.id):
                        hours_str = f"{total_minutes // 60}h {total_minutes % 60}m" if total_minutes > 0 else "0h"
                        await create_notification(
                            db,
                            user_id=user.id,
                            type=TIMESHEET_INCOMPLETE,
                            title=f"Timesheet incompleto: {u.full_name}",
                            message=f"{u.full_name} registró solo {hours_str} ayer ({yesterday.strftime('%d/%m')})",
                            link_url="/timesheet",
                            entity_type="user",
                            entity_id=u.id,
                        )
                        created += 1
        except Exception as e:
            logger.error("Error checking incomplete timesheets: %s", e)

    # 6. Active clients with 0 hours this week
    if user.role == UserRole.admin:
        try:
            # Start of current week (Monday)
            week_start = today - timedelta(days=today.weekday())
            active_clients_result = await db.execute(
                select(Client).where(Client.status == ClientStatus.active)
            )
            active_clients = active_clients_result.scalars().all()

            # Batch: get hours per client this week (1 query)
            client_hours_result = await db.execute(
                select(
                    Task.client_id,
                    func.coalesce(func.sum(TimeEntry.minutes), 0).label("total"),
                )
                .join(Task, TimeEntry.task_id == Task.id)
                .where(func.date(TimeEntry.date) >= week_start)
                .group_by(Task.client_id)
            )
            client_hours_map = {row.client_id: row.total for row in client_hours_result.all()}

            # Only alert from Wednesday onward (give Mon-Tue to start work)
            if today.weekday() >= 2:
                for client in active_clients:
                    if client_hours_map.get(client.id, 0) == 0 and not _has_existing(CLIENT_NO_HOURS, "client", client.id):
                        await create_notification(
                            db,
                            user_id=user.id,
                            type=CLIENT_NO_HOURS,
                            title=f"Sin horas: {client.name}",
                            message=f"El cliente {client.name} no tiene horas registradas esta semana",
                            link_url=f"/clients/{client.id}",
                            entity_type="client",
                            entity_id=client.id,
                        )
                        created += 1
        except Exception as e:
            logger.error("Error checking client hours: %s", e)

    # 7. Capacity overload — users with 20+ hours of pending estimated work
    try:
        overloaded_users = await db.execute(
            select(
                Task.assigned_to,
                func.sum(Task.estimated_minutes).label("total_est"),
            ).where(
                Task.assigned_to.isnot(None),
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                Task.estimated_minutes.isnot(None),
            ).group_by(Task.assigned_to)
        )

        # Collect overloaded user IDs, then batch-fetch names (1 query)
        overloaded_rows = [
            (row.assigned_to, row.total_est)
            for row in overloaded_users.all()
            if row.total_est and row.total_est > 1200
        ]
        if overloaded_rows:
            overloaded_ids = [r[0] for r in overloaded_rows]
            users_result = await db.execute(
                select(User).where(User.id.in_(overloaded_ids))
            )
            user_name_map = {u.id: u.full_name for u in users_result.scalars().all()}

            for assigned_to, total_est in overloaded_rows:
                if not _has_existing(CAPACITY_OVERLOAD, "user", assigned_to):
                    name = user_name_map.get(assigned_to, f"Usuario #{assigned_to}")
                    hours = total_est // 60
                    await create_notification(
                        db,
                        user_id=user.id,
                        type=CAPACITY_OVERLOAD,
                        title=f"Sobrecargado: {name}",
                        message=f"{name} tiene {hours}h+ de trabajo estimado pendiente",
                        link_url="/capacity",
                        entity_type="user",
                        entity_id=assigned_to,
                    )
                    created += 1
    except Exception as e:
        logger.error("Error checking capacity overload: %s", e)

    if created > 0:
        await db.commit()

    return {"created": created}
