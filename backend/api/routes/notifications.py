"""In-app notifications API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Notification
from backend.schemas.notification import NotificationResponse
from backend.services.incidents import reconcile_recipient
from backend.services.notification_checks import visible_notification_condition

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
        q = select(Notification).where(
            Notification.user_id == user.id, visible_notification_condition(user.id)
        )
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(q)
        return [NotificationResponse.model_validate(n) for n in result.scalars().all()]
    except Exception as e:
        logger.error("Error listing notifications for user %d: %s", user.id, e)
        raise


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
                visible_notification_condition(user.id),
            )
        )
        count = result.scalar() or 0
        return {"count": count}
    except Exception as e:
        logger.error("Error counting unread notifications for user %d: %s", user.id, e)
        raise


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
            visible_notification_condition(user.id),
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
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
            visible_notification_condition(user.id),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /generate-checks — Compatibility alias for canonical incident reconciliation
# ---------------------------------------------------------------------------


@router.post("/generate-checks")
async def generate_notification_checks(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Reconcile the canonical incident inbox for legacy API clients.

    The former generator produced an independent family of periodic rows.
    Keeping this route as an alias avoids breaking old clients while ensuring
    one identity, lifecycle and permission model for every current condition.
    """
    result = await reconcile_recipient(db, user.id)
    await db.commit()
    return result
