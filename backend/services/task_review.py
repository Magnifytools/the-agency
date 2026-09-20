"""Fresh policy checks for optional human review of project tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, TaskStatus, User, UserRole


@dataclass(frozen=True)
class TaskReviewContext:
    """Effective policy observed while holding the project against changes."""

    project_id: int | None
    requires_review: bool
    owner_id: int | None


def _effective(data: Mapping[str, Any], existing: Any, key: str, default: Any = None) -> Any:
    if key in data:
        return data[key]
    return getattr(existing, key, default) if existing is not None else default


def _is_status(value: Any, expected: TaskStatus) -> bool:
    return value == expected or value == expected.value


def _same_status(left: Any, right: Any) -> bool:
    left_value = left.value if isinstance(left, TaskStatus) else left
    right_value = right.value if isinstance(right, TaskStatus) else right
    return left_value == right_value


async def validate_project_review(
    db: AsyncSession,
    data: Mapping[str, Any],
    existing: Project | None = None,
) -> None:
    """Require an explicit active owner whenever review becomes effective.

    The caller must lock ``existing`` before invoking this validator. Creates
    have no existing row to race. Disabling review deliberately permits the
    historical nullable owner contract.
    """
    if data.get("requires_task_review", False) is None:
        raise HTTPException(422, "Indica si el proyecto requiere revisión de tareas")
    requires_review = bool(_effective(data, existing, "requires_task_review", False))
    if not requires_review:
        return
    if existing is not None:
        policy_changed = (
            "requires_task_review" in data
            and bool(data["requires_task_review"]) != bool(existing.requires_task_review)
        )
        owner_changed = "owner_id" in data and data["owner_id"] != existing.owner_id
        if not policy_changed and not owner_changed:
            return

    owner_id = _effective(data, existing, "owner_id")
    if owner_id is None:
        raise HTTPException(
            422,
            "Selecciona un responsable activo antes de activar la revisión de tareas",
        )
    try:
        active = (await db.execute(
            select(User.is_active)
            .where(User.id == owner_id)
            .with_for_update(read=True, nowait=True)
        )).scalar_one_or_none()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409,
                "El responsable del proyecto está cambiando; vuelve a intentarlo",
            ) from exc
        raise
    if active is None:
        raise HTTPException(422, "El responsable seleccionado no existe")
    if active is not True:
        raise HTTPException(422, "El responsable seleccionado no está activo")


async def validate_task_review(
    db: AsyncSession,
    data: Mapping[str, Any],
    actor: User | None,
    existing: Any = None,
    *,
    acquire_lock: bool = True,
) -> TaskReviewContext:
    """Validate an attempted task state against the project's fresh policy.

    The shared NOWAIT project lock lets concurrent task writers proceed while
    preventing owner/policy changes until commit. If a caller already holds a
    Task lock in the inverse order, contention becomes an actionable 409 rather
    than a deadlock.
    """
    if existing is not None:
        changes_policy_scope = any(
            key in data and not (
                _same_status(data[key], getattr(existing, key))
                if key == "status"
                else data[key] == getattr(existing, key)
            )
            for key in ("status", "project_id", "is_recurring")
        )
        if not changes_policy_scope:
            return TaskReviewContext(existing.project_id, False, None)

    project_id = _effective(data, existing, "project_id")
    status = _effective(data, existing, "status", TaskStatus.pending)
    is_recurring = bool(_effective(data, existing, "is_recurring", False))
    if not _is_status(status, TaskStatus.completed):
        return TaskReviewContext(project_id, False, None)

    project_ids: set[int] = set()
    if project_id is not None and not is_recurring:
        project_ids.add(project_id)
    if existing is not None and not existing.is_recurring and existing.project_id is not None:
        # A concrete task cannot evade its current review policy by becoming a
        # template or moving projects in the same completion mutation.
        project_ids.add(existing.project_id)
        if project_id is not None:
            project_ids.add(project_id)
    if not project_ids:
        return TaskReviewContext(project_id, False, None)

    statement = (
        select(
            Project.id,
            Project.requires_task_review,
            Project.owner_id,
        )
        .where(Project.id.in_(sorted(project_ids)))
        .order_by(Project.id)
    )
    if acquire_lock:
        statement = statement.with_for_update(read=True, nowait=True)
    try:
        rows = (await db.execute(statement)).all()
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if acquire_lock and sqlstate == "55P03":
            raise HTTPException(
                409,
                "La revisión del proyecto está cambiando; vuelve a intentarlo",
            ) from exc
        raise
    if not rows:
        # Project existence/FK ownership remains the task writer's contract.
        return TaskReviewContext(project_id, False, None)
    review_rows = [row for row in rows if row.requires_task_review]
    effective_row = next((row for row in rows if row.id == project_id), rows[0])
    if not review_rows:
        return TaskReviewContext(project_id, False, effective_row.owner_id)

    actor_id = getattr(actor, "id", None)
    actor_row = None
    if actor_id is not None:
        try:
            actor_row = (await db.execute(
                select(User.role, User.is_active)
                .where(User.id == actor_id)
                .with_for_update(read=True, nowait=True)
            )).one_or_none()
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise HTTPException(
                    409,
                    "Tus permisos están cambiando; vuelve a intentarlo",
                ) from exc
            raise
    privileged = bool(
        actor_row
        and actor_row.is_active
        and (
            actor_row.role == UserRole.admin
            or all(actor_id == row.owner_id for row in review_rows)
        )
    )
    if not privileged:
        raise HTTPException(
            409,
            "Este proyecto requiere revisión: envía la tarea con status=in_review para que la cierre su responsable",
        )
    return TaskReviewContext(project_id, True, effective_row.owner_id)
