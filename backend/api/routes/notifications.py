from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.db.models import Notification
from backend.api.deps import get_current_user
from backend.schemas.notification import NotificationResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[NotificationResponse]:
    """List notifications for the current user."""
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.is_read == False)
    q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return [NotificationResponse.model_validate(n) for n in result.scalars().all()]


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Get unread notification count for the current user."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read == False,
        )
    )
    count = result.scalar() or 0
    return {"count": count}


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


@router.put("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Mark all notifications as read for the current user."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}
