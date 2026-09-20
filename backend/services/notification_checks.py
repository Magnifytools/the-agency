"""Persistent identity for periodic checks, independent of read/unread state.

One batch per recipient locks their user row before loading existing checks.
This serializes concurrent generators and retains the batch-query behaviour.
Each condition supplies its own cycle (due date, reporting month, etc.).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import noload

from backend.core.modules import is_enabled
from backend.db.models import Notification, User


def visible_notification_condition():
    hidden_types = []
    for module, types in (
        ("billing", ["billing_reminder"]),
        ("leads", ["lead_followup"]),
        ("capacity", ["capacity_overload"]),
    ):
        if not is_enabled(module):
            hidden_types.extend(types)
    return and_(Notification.incident_state.is_(None), Notification.type.notin_(hidden_types))


class NotificationChecks:
    def __init__(self, db, user_id: int, rows: list[Notification]):
        self.db = db
        self.user_id = user_id
        self.rows = rows
        self.keys = {n.dedupe_key for n in rows if n.dedupe_key}
        self.cycles: dict[tuple[str, str, int], date] = {}

    @classmethod
    async def load(cls, db, user_id: int):
        await db.execute(select(User.id).where(User.id == user_id).with_for_update())
        result = await db.execute(select(Notification).options(noload("*")).where(Notification.user_id == user_id))
        return cls(db, user_id, list(result.scalars().all()))

    def has(self, kind: str, entity: str, entity_id: int, cycle: date) -> bool:
        identity = (kind, entity, entity_id)
        self.cycles[identity] = cycle
        key = f"{kind}:{entity}:{entity_id}:{cycle.isoformat()}"
        if key in self.keys:
            return True
        # Adopt an existing legacy check, including one already read. Billing
        # starts three days before its due date. Never delete historical rows.
        start = cycle - timedelta(days=3) if kind == "billing_reminder" else cycle
        for row in self.rows:
            if (row.type, row.entity_type, row.entity_id) != identity or row.dedupe_key:
                continue
            if row.created_at and row.created_at.date() >= start:
                row.dedupe_key = key
                self.keys.add(key)
                return True
        return False

    async def create(self, *, type: str, entity_type: str, entity_id: int, **fields):
        cycle = self.cycles[(type, entity_type, entity_id)]
        key = f"{type}:{entity_type}:{entity_id}:{cycle.isoformat()}"
        if key in self.keys:
            return None
        notification = Notification(
            user_id=self.user_id, type=type, entity_type=entity_type,
            entity_id=entity_id, dedupe_key=key, **fields,
        )
        self.db.add(notification)
        self.keys.add(key)
        self.rows.append(notification)
        return notification
