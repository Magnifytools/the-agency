"""Notification service — central place for creating in-app notifications."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Notification

logger = logging.getLogger(__name__)

# Notification type constants
TASK_ASSIGNED = "task_assigned"
TASK_OVERDUE = "task_overdue"
LEAD_FOLLOWUP = "lead_followup"
DIGEST_GENERATED = "digest_generated"
PHASE_COMPLETED = "phase_completed"


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int,
    type: str,
    title: str,
    message: Optional[str] = None,
    link_url: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
) -> Notification | None:
    """Create a notification for a user.

    Does NOT commit — the caller must commit the session.
    This allows batching notification creation with other DB writes
    in a single transaction.

    Returns the Notification or None on error (never breaks the caller).
    """
    try:
        notif = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            link_url=link_url,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        db.add(notif)
        return notif
    except Exception as e:
        logger.error("Failed to create notification for user %d: %s", user_id, e)
        return None
