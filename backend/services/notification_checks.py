"""Persistent identity for periodic checks, independent of read/unread state.

One batch per recipient locks their user row before loading existing checks.
This serializes concurrent generators and retains the batch-query behaviour.
Each condition supplies its own cycle (due date, reporting month, etc.).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.orm import aliased, noload

from backend.core.modules import is_enabled
from backend.db.models import Notification, Project, Task, User, WeeklyDigest
from backend.services.incident_conditions import module_permission
from backend.services.task_notifications import TASK_ACTIVITY_TYPES
from backend.services.temporal import business_today

# These rows came from the retired ``/notifications/generate-checks`` writer.
# They remain stored as history, but the activity feed must not present stale
# checks beside the canonical incident inbox.
RETIRED_CHECK_TYPES = (
    "billing_reminder",
    "capacity_overload",
    "client_no_hours",
    "daily_missing",
    "lead_followup",
    "project_closing_overdue",
    "project_closing_soon",
    "project_monthly_hours_exceeded",
    "project_monthly_hours_warning",
    "task_overdue",
    "timesheet_incomplete",
)
UNSCOPED_RETIRED_TYPES = ("automation",)


def visible_notification_condition(user_id: int):
    """Scope activity before pagination, counting or read-state mutations.

    Source-backed notifications require both a valid source and the current
    module permission. Scheduled task summaries have no source ID and cannot
    be redacted after rendering, so loss of task access hides the whole row.
    """
    # The retired automation writer stored arbitrary text without a source ID.
    # Its historical rows cannot be safely scoped to a current entity.
    hidden_types = (*RETIRED_CHECK_TYPES, *UNSCOPED_RETIRED_TYPES)
    task_read = module_permission(user_id, "tasks") if is_enabled("tasks") else false()
    project_read = module_permission(user_id, "projects") if is_enabled("projects") else false()
    digest_read = module_permission(user_id, "digests") if is_enabled("digests") else false()
    task_activity = ("task_assigned",)
    # Revisión tras publicar (services/web/publish_check.py) y comentarios,
    # menciones, revisión y "vence mañana" (services/task_notifications.py): se
    # ven mientras se pueda leer la tarea, aunque luego se reasigne.
    task_checks = ("task_publish_check", *TASK_ACTIVITY_TYPES)
    project_activity = ("phase_completed",)
    digest_activity = ("digest_generated",)
    task_summaries = ("scheduled_morning", "scheduled_evening")
    newer_assignment = aliased(Notification)
    return and_(
        Notification.incident_state.is_(None),
        Notification.type.notin_(hidden_types),
        or_(
            and_(Notification.type.in_(task_activity), Notification.entity_type == "task",
                 task_read, exists().where(
                     Task.id == Notification.entity_id, Task.assigned_to == user_id,
                 ),
                 ~exists().where(
                     newer_assignment.user_id == Notification.user_id,
                     newer_assignment.type == "task_assigned",
                     newer_assignment.incident_state.is_(None),
                     newer_assignment.entity_type == "task",
                     newer_assignment.entity_id == Notification.entity_id,
                     newer_assignment.id > Notification.id,
                 )),
            and_(Notification.type.in_(project_activity), Notification.entity_type == "project",
                 project_read, exists().where(Project.id == Notification.entity_id)),
            and_(Notification.type.in_(digest_activity), Notification.entity_type == "digest",
                 digest_read, exists().where(WeeklyDigest.id == Notification.entity_id)),
            and_(Notification.type.in_(task_summaries), task_read),
            and_(Notification.type.in_(task_checks), Notification.entity_type == "task",
                 task_read, exists().where(Task.id == Notification.entity_id)),
            Notification.type.notin_((*task_activity, *project_activity, *digest_activity, *task_summaries,
                                      *task_checks)),
        ),
    )


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
        result = await db.execute(
            select(Notification)
            .options(noload("*"))
            .where(Notification.user_id == user_id)
        )
        return cls(db, user_id, list(result.scalars().all()))

    def has(self, kind: str, entity: str, entity_id: int, cycle: date) -> bool:
        identity = (kind, entity, entity_id)
        self.cycles[identity] = cycle
        key = f"{kind}:{entity}:{entity_id}:{cycle.isoformat()}"
        if key in self.keys:
            return True
        # Adopt an existing legacy check, including one already read. Never
        # delete historical rows.
        for row in self.rows:
            if (row.type, row.entity_type, row.entity_id) != identity or row.dedupe_key:
                continue
            # created_at es UTC sin zona y el ciclo es un día de Madrid: entre las
            # 23:00 y las 00:00 UTC la fecha UTC aún es la de ayer allí.
            if row.created_at and business_today(now=row.created_at) >= cycle:
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
            user_id=self.user_id,
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            dedupe_key=key,
            **fields,
        )
        self.db.add(notification)
        self.keys.add(key)
        self.rows.append(notification)
        return notification
