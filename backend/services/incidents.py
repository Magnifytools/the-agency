"""Canonical operational conditions on Notification; reads never reconcile.

Reconciliation and decisions share a short recipient lock. A deadline is the
cycle, not today's date: routine aging cannot undo a person's decision.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib

from fastapi import HTTPException
from sqlalchemy import Date, and_, cast, exists, false, func, or_, select
from sqlalchemy.orm import noload

from backend.core.modules import is_enabled
from backend.db.models import Notification, Task, TaskStatus, User, UserPermission, UserRole
from backend.schemas.incident import IncidentDecision, IncidentResponse
from backend.services.incident_conditions import Condition
from backend.services.incident_project_conditions import (
    PROJECT_CONDITIONS, collect_project_conditions, project_visibility_clause,
)
from backend.services.incident_report_conditions import (
    REPORT_CONDITIONS, collect_report_conditions, report_visibility_clause,
)
from backend.services.temporal import as_utc_instant, business_today, utc_now_naive

TASK_CONDITIONS = ("task_overdue", "task_waiting_followup")
SUPPORTED_CONDITIONS = TASK_CONDITIONS + PROJECT_CONDITIONS + REPORT_CONDITIONS
OPEN_STATES = ("active", "snoozed", "dismissed")


def task_permission(user_id):
    return or_(
        User.role == UserRole.admin,
        exists().where(UserPermission.user_id == user_id, UserPermission.module == "tasks", UserPermission.can_read.is_(True)),
    )


async def recipient_access(db, user_id: int, *, lock=False):
    if lock:
        # Serialize reconciliations without blocking FK KEY SHARE locks when a
        # task writer changes its assignee while already holding the task lock.
        await db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    # A separate statement gets a fresh snapshot after waiting for the lock:
    # permission replacement changes child rows without updating User itself.
    stmt = select(User.id, User.is_active, task_permission(User.id).label("tasks_read")).where(User.id == user_id)
    return (await db.execute(stmt)).one_or_none()


def live_task_condition_clause():
    today = business_today()
    cycle_key = lambda date_column: func.concat(Notification.type, ":task:", Task.id, ":", func.to_char(date_column, "YYYY-MM-DD"))
    return exists().where(
        Task.id == Notification.entity_id, Task.assigned_to == Notification.user_id,
        Task.status != TaskStatus.completed, Task.is_recurring.is_(False),
        or_(
            and_(Notification.type == "task_overdue", cast(Task.due_date, Date) < today, Notification.dedupe_key == cycle_key(Task.due_date)),
            and_(Notification.type == "task_waiting_followup", Task.status == TaskStatus.waiting, Task.follow_up_date <= today, Notification.dedupe_key == cycle_key(Task.follow_up_date)),
        ),
    )


def task_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled("tasks"):
        return false()
    return and_(
        Notification.entity_type == "task",
        Notification.type.in_(TASK_CONDITIONS),
        live_task_condition_clause() if current_only else exists().where(
            Task.id == Notification.entity_id, Task.assigned_to == user_id,
        ),
        exists().where(User.id == user_id, User.is_active.is_(True), task_permission(User.id)),
    )


def visible_incident_clause(user_id: int, *, current_only: bool = False):
    """Apply current source permissions even before the next background pass."""
    return and_(
        Notification.user_id == user_id,
        Notification.incident_state.is_not(None),
        exists().where(User.id == user_id, User.is_active.is_(True)),
        or_(
            task_visibility_clause(user_id, current_only=current_only),
            project_visibility_clause(user_id, current_only=current_only),
            report_visibility_clause(user_id, current_only=current_only),
        ),
    )


async def collect_task_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    today = business_today(now=now)
    due = and_(Task.due_date.is_not(None), cast(Task.due_date, Date) < today)
    waiting = and_(Task.status == TaskStatus.waiting, Task.follow_up_date.is_not(None), Task.follow_up_date <= today)
    rows = (await db.execute(select(
        Task.id, Task.title, Task.due_date, Task.status, Task.follow_up_date, Task.waiting_for,
    ).where(
        Task.assigned_to == user_id, Task.status != TaskStatus.completed,
        Task.is_recurring.is_(False), or_(due, waiting),
    ).order_by(Task.id).with_for_update())).all()
    result = {}
    for task in rows:
        conditions = []
        if task.due_date and task.due_date.date() < today:
            conditions.append(("task_overdue", task.due_date.date(), f"Tarea vencida: {task.title}", f"El compromiso venció el {task.due_date:%d/%m/%Y}. Revisa la tarea o su fecha."))
        if task.status == TaskStatus.waiting and task.follow_up_date and task.follow_up_date <= today:
            message = f"El seguimiento estaba previsto para el {task.follow_up_date:%d/%m/%Y}."
            if task.waiting_for:
                message += f" En espera de: {task.waiting_for}."
            conditions.append(("task_waiting_followup", task.follow_up_date, f"Revisar espera: {task.title}", message))
        for kind, cycle, title, message in conditions:
            key = f"{kind}:task:{task.id}:{cycle.isoformat()}"
            # Copy edits and normal daily aging do not establish a new promise.
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            result[key] = Condition(
                key, kind, task.id, title[:255], message, fingerprint,
                entity_key=str(task.id), href=f"/tasks?task={task.id}",
                legacy_since=datetime.combine(cycle, datetime.min.time()),
            )
    return result


def _snapshot(row):
    return tuple(getattr(row, field) for field in (
        "type", "title", "message", "link_url", "entity_key", "incident_state", "incident_detected_at",
        "incident_severity", "incident_fingerprint", "incident_snoozed_until",
        "incident_resolved_at", "incident_resolution_reason", "incident_dismissal_reason",
    ))


async def reconcile_recipient(db, user_id: int, *, now: datetime | None = None):
    """Reconcile supported conditions inside the caller's transaction; no commit."""
    now = as_utc_instant(now or utc_now_naive()).replace(tzinfo=None)
    actor = await recipient_access(db, user_id, lock=True)
    if actor is None:
        return {"created": 0, "changed": 0}
    allowed = actor.is_active and actor.tasks_read and is_enabled("tasks")
    candidates = await collect_task_conditions(db, user_id, now) if allowed else {}
    if actor.is_active:
        candidates.update(await collect_project_conditions(db, user_id, now))
        candidates.update(await collect_report_conditions(db, user_id, now))
    legacy_sources = [and_(
        Notification.type == condition.kind,
        Notification.entity_type == condition.entity_type,
        Notification.entity_id == condition.entity_id,
        Notification.created_at >= condition.legacy_since,
    ) for condition in candidates.values() if condition.legacy_since is not None and condition.entity_id is not None]
    records = (await db.execute(select(
        Notification, visible_incident_clause(user_id).label("source_visible"),
    ).options(noload("*")).where(
        Notification.user_id == user_id,
        Notification.type.in_(SUPPORTED_CONDITIONS),
        or_(
            Notification.incident_state.in_(OPEN_STATES),
            Notification.dedupe_key.in_(list(candidates)),
            and_(Notification.incident_state.is_(None), Notification.dedupe_key.is_(None), or_(*legacy_sources) if legacy_sources else false()),
        ),
    ).order_by(Notification.id))).all()
    rows = [record[0] for record in records]
    source_visible = {record[0].id: record[1] for record in records}
    keyed = {row.dedupe_key: row for row in rows if row.dedupe_key}
    adopted_ids = set()
    created = changed = 0
    for key, condition in candidates.items():
        row = keyed.get(key)
        if row is None:
            # Adopt only a legacy check that can actually belong to this cycle.
            row = next((value for value in rows if (
                condition.legacy_since is not None and value.id not in adopted_ids
                and value.dedupe_key is None and value.type == condition.kind
                and value.entity_type == condition.entity_type
                and value.entity_id == condition.entity_id
                and value.created_at and value.created_at >= condition.legacy_since
            )), None)
            if row is not None:
                adopted_ids.add(row.id)
                row.dedupe_key = key
            else:
                row = Notification(user_id=user_id, type=condition.kind, title=condition.title, entity_type=condition.entity_type, entity_id=condition.entity_id, dedupe_key=key, created_at=now, updated_at=now)
                db.add(row)
                created += 1
        before = _snapshot(row)
        if row.incident_detected_at is None:
            # The legacy event timestamp may be local time. Preserve it and
            # record when this operational condition was first observed in UTC.
            row.incident_detected_at = now
        same_condition = row.incident_fingerprint == condition.fingerprint
        if not same_condition:
            row.incident_dismissal_reason = None
            row.incident_snoozed_until = None
        row.incident_state = (
            "dismissed" if row.incident_dismissal_reason else
            "snoozed" if row.incident_snoozed_until and row.incident_snoozed_until > now else "active"
        )
        row.incident_resolved_at = None
        row.incident_resolution_reason = None
        row.incident_fingerprint = condition.fingerprint
        row.incident_severity = condition.severity
        row.title, row.message = condition.title, condition.message
        row.link_url = condition.href
        row.entity_key = condition.entity_key
        if before != _snapshot(row):
            row.incident_revision = (row.incident_revision or 0) + 1
            row.updated_at = now
            changed += 1
    for row in rows:
        if row.dedupe_key in candidates or row.incident_state not in OPEN_STATES:
            continue
        row.incident_state = "resolved"
        row.incident_resolved_at = now
        row.incident_resolution_reason = "condition_cleared" if source_visible.get(row.id) else "permission_lost"
        row.incident_revision += 1
        row.updated_at = now
        changed += 1
    await db.flush()
    return {"created": created, "changed": changed}


def incident_response(row: Notification) -> IncidentResponse:
    return IncidentResponse(
        id=row.id, revision=row.incident_revision, condition_type=row.type,
        state=row.incident_state, severity=row.incident_severity,
        title=row.title, message=row.message, href=row.link_url,
        entity_type=row.entity_type, entity_key=row.entity_key,
        created_at=row.incident_detected_at, snoozed_until=row.incident_snoozed_until,
        resolved_at=row.incident_resolved_at, resolution_reason=row.incident_resolution_reason,
        dismissal_reason=row.incident_dismissal_reason,
    )


async def decide_incident(db, user_id: int, incident_id: int, request: IncidentDecision, *, now=None):
    now = as_utc_instant(now or utc_now_naive()).replace(tzinfo=None)
    # This also acquires the recipient lock before reading the decision row.
    # A changed source can resolve the condition; there is no generic Resolve.
    await reconcile_recipient(db, user_id, now=now)
    row = (await db.execute(select(Notification).options(noload("*")).where(
        Notification.id == incident_id, visible_incident_clause(user_id),
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Aviso no disponible")
    if row.incident_revision != request.revision or row.incident_state == "resolved":
        raise HTTPException(409, detail={"code": "incident_changed", "current": incident_response(row).model_dump(mode="json")})
    if request.action == "snooze":
        until = as_utc_instant(request.until).replace(tzinfo=None)
        if not now < until <= now + timedelta(days=30):
            raise HTTPException(422, "Elige una fecha futura dentro de los próximos 30 días")
        row.incident_state = "snoozed"
        row.incident_snoozed_until = until
        row.incident_dismissal_reason = None
    elif request.action == "dismiss":
        row.incident_state = "dismissed"
        row.incident_dismissal_reason = request.reason
        row.incident_snoozed_until = None
    else:
        row.incident_state = "active"
        row.incident_dismissal_reason = None
        row.incident_snoozed_until = None
    row.incident_revision += 1
    row.updated_at = now
    await db.flush()
    return incident_response(row)


async def reconcile_all(session_factory, *, now: datetime | None = None):
    """Page recipients and commit each separately so one failure is recoverable."""
    import logging
    totals = {"recipients": 0, "created": 0, "changed": 0, "failed": 0}
    after_id = 0
    while True:
        async with session_factory() as db:
            ids = list((await db.execute(select(User.id).where(
                User.id > after_id,
                or_(User.is_active.is_(True), exists().where(
                    Notification.user_id == User.id,
                    Notification.incident_state.in_(OPEN_STATES),
                    Notification.type.in_(SUPPORTED_CONDITIONS),
                )),
            ).order_by(User.id).limit(100))).scalars())
        if not ids:
            return totals
        for user_id in ids:
            async with session_factory() as db:
                try:
                    result = await reconcile_recipient(db, user_id, now=now)
                    await db.commit()
                    totals["recipients"] += 1
                    totals["created"] += result["created"]
                    totals["changed"] += result["changed"]
                except Exception as exc:
                    await db.rollback()
                    totals["failed"] += 1
                    logging.getLogger(__name__).error("Incident reconciliation failed user_id=%s type=%s", user_id, type(exc).__name__)
        after_id = ids[-1]


async def incident_loop():
    import asyncio
    from backend.db.database import async_session
    while True:
        try:
            await reconcile_all(async_session)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Incident recipient scan failed type=%s", type(exc).__name__)
        await asyncio.sleep(30)
