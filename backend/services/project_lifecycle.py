"""Explicit, reviewable project close/reopen transitions.

Lock order is shared with recurrence and destructive scope writers:
global advisory -> current ACL -> Project -> Tasks -> active TimeEntries.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.core.modules import is_enabled
from backend.db.models import (
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserPermission,
    UserRole,
)
from backend.schemas.project import (
    ProjectCloseBlockers,
    ProjectClosePreview,
    ProjectLifecycleCount,
    ProjectLifecycleRecurrence,
    ProjectLifecycleTaskSample,
    ProjectLifecycleTimerSample,
    ProjectReopenPreview,
)
from backend.services.temporal import as_utc_instant
from backend.services.write_access import require_current_write

PROJECT_LIFECYCLE_LOCK = 76241317
SAMPLE_LIMIT = 20
ARCHIVED_STATUSES = {ProjectStatus.completed, ProjectStatus.cancelled}
OPERATING_STATUSES = {ProjectStatus.planning, ProjectStatus.active, ProjectStatus.on_hold}

TASK_PROJECT_STATE_FIELDS = (
    "project_id", "status", "retired_at", "is_recurring", "recurrence_paused_at",
)


def _status(value: ProjectStatus | str) -> ProjectStatus:
    try:
        return value if isinstance(value, ProjectStatus) else ProjectStatus(value)
    except ValueError as exc:
        raise HTTPException(422, "Estado de proyecto no válido") from exc


def _epoch(value: datetime) -> Decimal:
    instant = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    delta = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return Decimal((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) / Decimal(1_000_000)


def _iso(value: datetime | None) -> str | None:
    instant = as_utc_instant(value)
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z") if instant else None


def task_project_state(task: Task | None = None, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build an immutable lifecycle snapshot before an ORM row is mutated."""
    data = dict(overrides or {})
    return {
        field: data[field] if field in data else getattr(task, field, None)
        for field in TASK_PROJECT_STATE_FIELDS
    }


def _task_state_is_operational(state: Mapping[str, Any]) -> bool:
    status = getattr(state.get("status"), "value", state.get("status"))
    if state.get("retired_at") is not None or status == TaskStatus.completed.value:
        return False
    if bool(state.get("is_recurring")):
        return state.get("recurrence_paused_at") is None
    return True


def _same_task_lifecycle(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    def normalized(state: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            state.get("project_id"),
            getattr(state.get("status"), "value", state.get("status")),
            state.get("retired_at") is not None,
            bool(state.get("is_recurring")),
            state.get("recurrence_paused_at") is not None,
        )
    return normalized(left) == normalized(right)


async def ensure_project_allows_task_state(
    db: AsyncSession, *, state: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None = None,
    creating: bool = False, allow_historical_restore: bool = False,
) -> None:
    """Serialize a task result against project archival.

    ``previous_state`` must be captured before mutating the ORM object.  Undo
    may opt into ``allow_historical_restore`` only for an explicit reinsert;
    the resulting row still has to be completed, retired, or a paused template.
    """
    project_id = state.get("project_id")
    if project_id is None:
        return
    try:
        status = await db.scalar(
            select(Project.status).where(Project.id == project_id)
            .with_for_update(read=True, nowait=True)
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(409, "El proyecto está cambiando; vuelve a intentarlo") from exc
        raise
    if status is None or _status(status) not in ARCHIVED_STATUSES:
        return

    operational = _task_state_is_operational(state)
    if creating:
        if allow_historical_restore and not operational:
            return
        raise HTTPException(409, "Reabre el proyecto antes de crear trabajo nuevo")
    if previous_state is not None and _same_task_lifecycle(state, previous_state):
        return
    if not operational:
        return
    raise HTTPException(409, "Reabre el proyecto antes de activar trabajo")


async def ensure_project_allows_timer(db: AsyncSession, task: Task) -> None:
    """Reject new running time against a freshly locked archived project."""
    state = task_project_state(task)
    project_id = state["project_id"]
    if project_id is None:
        return
    try:
        status = await db.scalar(
            select(Project.status).where(Project.id == project_id)
            .with_for_update(read=True, nowait=True)
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(409, "El proyecto está cambiando; vuelve a intentarlo") from exc
        raise
    if status is not None and _status(status) in ARCHIVED_STATUSES:
        raise HTTPException(409, "Reabre el proyecto antes de iniciar el timer")


async def _module_readable(db: AsyncSession, actor: User | None, module: str) -> bool:
    if actor is None or not is_enabled(module):
        return False
    row = (await db.execute(select(User.role, User.is_active).where(User.id == actor.id))).one_or_none()
    if row is None or row.is_active is not True:
        return False
    if row.role == UserRole.admin:
        return True
    return bool(await db.scalar(select(UserPermission.can_read).where(
        UserPermission.user_id == actor.id,
        UserPermission.module == module,
        UserPermission.can_read.is_(True),
    )))


async def _project_row(db: AsyncSession, project_id: int, *, lock: bool) -> tuple[Project, Decimal]:
    stmt = (
        select(Project, func.extract("epoch", Project.updated_at).label("updated_epoch"))
        .where(Project.id == project_id).options(noload("*"))
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(404, "Project not found")
    return row[0], Decimal(row[1])


async def _decision_rows(db: AsyncSession, project_id: int, *, lock: bool):
    task_stmt = (
        select(Task).where(Task.project_id == project_id).options(noload("*"))
        .order_by(Task.id)
    )
    if lock:
        task_stmt = task_stmt.with_for_update().execution_options(populate_existing=True)
    tasks = list((await db.execute(task_stmt)).scalars())
    timer_stmt = (
        select(TimeEntry)
        .join(Task, Task.id == TimeEntry.task_id)
        .where(Task.project_id == project_id, TimeEntry.minutes.is_(None))
        .options(noload("*")).order_by(TimeEntry.id)
    )
    if lock:
        timer_stmt = timer_stmt.with_for_update(of=TimeEntry).execution_options(populate_existing=True)
    timers = list((await db.execute(timer_stmt)).scalars())
    return tasks, timers


def _revision(project: Project, tasks: list[Task], timers: list[TimeEntry]) -> str:
    payload = {
        "version": 1,
        "project": [project.id, _status(project.status).value, _iso(project.updated_at)],
        "tasks": [[
            task.id,
            task.status.value if hasattr(task.status, "value") else str(task.status),
            _iso(task.retired_at),
            bool(task.is_recurring),
            _iso(task.recurrence_paused_at),
            task.project_id,
        ] for task in tasks],
        "timers": [[timer.id, timer.task_id, _iso(timer.started_at), _iso(timer.paused_at)] for timer in timers],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _recurrence(tasks: list[Task]) -> ProjectLifecycleRecurrence:
    templates = [task for task in tasks if task.retired_at is None and task.is_recurring]
    paused = sum(task.recurrence_paused_at is not None for task in templates)
    return ProjectLifecycleRecurrence(
        templates=len(templates), paused=paused,
        suppressed_after_close=len(templates) - paused,
    )


async def _close_preview(
    db: AsyncSession, project: Project, tasks: list[Task], timers: list[TimeEntry],
    target: ProjectStatus, actor: User | None,
) -> ProjectClosePreview:
    active = [task for task in tasks if (
        task.retired_at is None and not task.is_recurring and task.status != TaskStatus.completed
    )]
    can_see_tasks = await _module_readable(db, actor, "tasks")
    can_see_timers = await _module_readable(db, actor, "timesheet")
    task_sample = [ProjectLifecycleTaskSample(
        id=task.id, title=task.title,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        href=f"/tasks?task={task.id}",
    ) for task in active[:SAMPLE_LIMIT]] if can_see_tasks else []
    timer_sample = [ProjectLifecycleTimerSample(
        id=timer.id, task_id=timer.task_id,
        href=f"/tasks?task={timer.task_id}" if can_see_tasks else None,
    ) for timer in timers[:SAMPLE_LIMIT]] if can_see_timers else []
    return ProjectClosePreview(
        project_id=project.id, target=target.value,
        current_status=_status(project.status).value,
        expected_updated_at=as_utc_instant(project.updated_at),
        preview_revision=_revision(project, tasks, timers),
        can_close=not active and not timers,
        blockers=ProjectCloseBlockers(
            active_tasks=ProjectLifecycleCount(total=len(active), sample=task_sample),
            waiting_count=sum(task.status == TaskStatus.waiting for task in active),
            in_review_count=sum(task.status == TaskStatus.in_review for task in active),
            active_timers=ProjectLifecycleCount(total=len(timers), sample=timer_sample),
        ),
        recurrence=_recurrence(tasks),
    )


async def get_close_preview(
    db: AsyncSession, project_id: int, target: str, actor: User,
) -> ProjectClosePreview:
    target_status = _status(target)
    if target_status not in ARCHIVED_STATUSES:
        raise HTTPException(422, "El cierre debe terminar o cancelar el proyecto")
    await require_current_write(db, actor, {"projects"})
    project, _ = await _project_row(db, project_id, lock=False)
    if _status(project.status) not in OPERATING_STATUSES:
        raise HTTPException(409, "El proyecto ya está archivado")
    tasks, timers = await _decision_rows(db, project_id, lock=False)
    return await _close_preview(db, project, tasks, timers, target_status, actor)


async def get_reopen_preview(
    db: AsyncSession, project_id: int, actor: User,
) -> ProjectReopenPreview:
    await require_current_write(db, actor, {"projects"})
    project, _ = await _project_row(db, project_id, lock=False)
    if _status(project.status) not in ARCHIVED_STATUSES:
        raise HTTPException(409, "El proyecto no está archivado")
    tasks, timers = await _decision_rows(db, project_id, lock=False)
    recurrence = _recurrence(tasks)
    return ProjectReopenPreview(
        project_id=project.id, current_status=_status(project.status).value,
        expected_updated_at=as_utc_instant(project.updated_at),
        preview_revision=_revision(project, tasks, timers), can_reopen=True,
        recurrence=recurrence,
        message="Las plantillas no pausadas volverán a operar desde la fecha civil actual.",
    )


async def acquire_project_lifecycle_lock(db: AsyncSession) -> None:
    """Acquire the shared project/recurrence transaction lock."""
    await db.execute(text(f"SELECT pg_advisory_xact_lock({PROJECT_LIFECYCLE_LOCK})"))


async def _locked_state(db: AsyncSession, project_id: int, actor: User | None):
    await acquire_project_lifecycle_lock(db)
    await require_current_write(db, actor, {"projects"})
    project, epoch = await _project_row(db, project_id, lock=True)
    tasks, timers = await _decision_rows(db, project_id, lock=True)
    return project, epoch, tasks, timers


async def validate_project_lifecycle_inverse(
    db: AsyncSession, *, project_id: int,
    previous_status: ProjectStatus | str, actor: User | None,
) -> None:
    """Validate an already-applied inverse while its lifecycle locks are held.

    Undo callers acquire the advisory lock before locking journal entities. The
    current Project row is the inverse result; ``previous_status`` is the
    immutable status captured before applying it.
    """
    await require_current_write(db, actor, {"projects"})
    project, _epoch_value = await _project_row(db, project_id, lock=True)
    current = _status(project.status)
    previous = _status(previous_status)
    if current not in ARCHIVED_STATUSES or previous in ARCHIVED_STATUSES:
        return
    tasks, timers = await _decision_rows(db, project_id, lock=True)
    preview = await _close_preview(db, project, tasks, timers, current, actor)
    if not preview.can_close:
        raise HTTPException(409, detail={
            "code": "project_close_blocked",
            "current_preview": preview.model_dump(mode="json"),
        })


def _changed(preview: Any) -> HTTPException:
    return HTTPException(409, detail={
        "code": "project_close_changed",
        "current_preview": preview.model_dump(mode="json"),
    })


async def close_project(
    db: AsyncSession, project_id: int, *, target: str,
    expected_updated_at: datetime, preview_revision: str, actor: User,
) -> Project:
    target_status = _status(target)
    if target_status not in ARCHIVED_STATUSES:
        raise HTTPException(422, "El cierre debe terminar o cancelar el proyecto")
    project, epoch, tasks, timers = await _locked_state(db, project_id, actor)
    if _status(project.status) not in OPERATING_STATUSES:
        raise HTTPException(409, "El proyecto ya está archivado")
    preview = await _close_preview(db, project, tasks, timers, target_status, actor)
    if epoch != _epoch(expected_updated_at) or preview.preview_revision != preview_revision:
        raise _changed(preview)
    if not preview.can_close:
        raise HTTPException(409, detail={
            "code": "project_close_blocked",
            "current_preview": preview.model_dump(mode="json"),
        })
    project.__dict__["_lifecycle_previous_status"] = _status(project.status).value
    project.status = target_status
    await db.flush()
    return project


async def reopen_project(
    db: AsyncSession, project_id: int, *, expected_updated_at: datetime,
    preview_revision: str, actor: User,
) -> Project:
    project, epoch, tasks, timers = await _locked_state(db, project_id, actor)
    if _status(project.status) not in ARCHIVED_STATUSES:
        raise HTTPException(409, "El proyecto no está archivado")
    preview = ProjectReopenPreview(
        project_id=project.id, current_status=_status(project.status).value,
        expected_updated_at=as_utc_instant(project.updated_at),
        preview_revision=_revision(project, tasks, timers), can_reopen=True,
        recurrence=_recurrence(tasks),
        message="Las plantillas no pausadas volverán a operar desde la fecha civil actual.",
    )
    if epoch != _epoch(expected_updated_at) or preview.preview_revision != preview_revision:
        raise _changed(preview)
    project.__dict__["_lifecycle_previous_status"] = _status(project.status).value
    project.status = ProjectStatus.active
    await db.flush()
    return project


async def transition_project_status(
    db: AsyncSession, project_id: int, target: ProjectStatus | str, actor: User | None,
) -> Project:
    """Apply a non-archive status transition under the recurrence lock protocol.

    Automation owners may pass ``actor=None`` only for an already-authorized
    system action. Archive transitions always require preview endpoints.
    """
    target_status = _status(target)
    project, _epoch_value, _tasks, _timers = await _locked_state(db, project_id, actor)
    current = _status(project.status)
    if current == target_status:
        return project
    if current in ARCHIVED_STATUSES or target_status in ARCHIVED_STATUSES:
        action = "reopen" if current in ARCHIVED_STATUSES else "close"
        raise HTTPException(409, detail={
            "code": "project_lifecycle_action_required", "action": action,
        })
    project.__dict__["_lifecycle_previous_status"] = current.value
    project.status = target_status
    await db.flush()
    return project
