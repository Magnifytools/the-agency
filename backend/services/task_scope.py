"""Shared hierarchy validation for every path that creates or edits a task."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Project, ProjectPhase, Task, User


async def _validate_dependency(
    db: AsyncSession, dependency_id: int | None, *, existing: Task | None,
) -> None:
    if dependency_id is None:
        return
    if existing is not None and dependency_id == existing.id:
        raise HTTPException(422, "Una tarea no puede depender de sí misma")
    # A real PostgreSQL FOR KEY SHARE is sufficient: retirement holds FOR
    # UPDATE, while unrelated non-key edits of the dependency stay concurrent.
    dependency = (await db.execute(
        select(Task.id, Task.retired_at)
        .where(Task.id == dependency_id)
        .with_for_update(read=True, key_share=True)
    )).one_or_none()
    if dependency is None:
        raise HTTPException(422, "La tarea de la que depende no existe")
    if dependency.retired_at is not None:
        raise HTTPException(409, "No se puede depender de una tarea retirada")


async def validate_client_exists(db: AsyncSession, client_id: int | None) -> None:
    """Reject an explicit dangling client while preserving internal unscoped work."""
    if client_id is None:
        return
    exists = (await db.execute(
        select(Client.id).where(Client.id == client_id)
    )).scalar_one_or_none()
    if exists is None:
        raise HTTPException(422, "El cliente seleccionado no existe")


async def validate_task_assignee(
    db: AsyncSession, assigned_to: int | None,
) -> None:
    """Require an active assignee for a new or genuinely reassigned task.

    Existing tasks may preserve a historical assignment after that person is
    deactivated, so unrelated edits deliberately do not revalidate it. A
    shared lock makes a simultaneous deactivation conflict instead of letting
    a stale assignment through.
    """
    if assigned_to is None:
        return
    try:
        active_user = await db.scalar(
            select(User.id).where(
                User.id == assigned_to,
                User.is_active.is_(True),
            ).with_for_update(read=True, nowait=True)
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409,
                "La persona asignada está cambiando; vuelve a intentarlo",
            ) from exc
        raise
    if active_user is None:
        raise HTTPException(422, "La persona asignada no existe o está inactiva")


async def validate_task_scope(
    db: AsyncSession, data: dict, *, existing: Task | None = None,
) -> None:
    """Resolve and validate client/project/phase ids, mutating ``data`` in place."""
    project_id = data.get("project_id", existing.project_id if existing else None)
    phase_id = data.get("phase_id", existing.phase_id if existing else None)
    client_id = data.get("client_id", existing.client_id if existing else None)
    assigned_to = data.get("assigned_to", existing.assigned_to if existing else None)

    if existing is None or (
        "assigned_to" in data and data["assigned_to"] != existing.assigned_to
    ):
        await validate_task_assignee(db, assigned_to)

    requested_status = data.get("status")
    requested_status_value = getattr(requested_status, "value", requested_status)
    existing_status_value = getattr(existing.status, "value", existing.status) if existing else None
    reopens_completed = (
        existing is not None
        and existing_status_value == "completed"
        and "status" in data
        and requested_status_value != "completed"
    )
    if existing is None or "depends_on" in data or reopens_completed:
        dependency_id = data.get("depends_on", existing.depends_on if existing else None)
        await _validate_dependency(db, dependency_id, existing=existing)

    await validate_client_exists(db, client_id)

    if existing is not None and "project_id" in data and "phase_id" not in data:
        if data["project_id"] != existing.project_id:
            phase_id = None
            data["phase_id"] = None

    if phase_id is not None:
        phase_project_id = (await db.execute(
            select(ProjectPhase.project_id).where(ProjectPhase.id == phase_id)
        )).scalar_one_or_none()
        if phase_project_id is None:
            raise HTTPException(422, "La fase seleccionada no existe")
        if project_id is None:
            project_id = phase_project_id
            data["project_id"] = project_id
        elif phase_project_id != project_id:
            raise HTTPException(422, "La fase no pertenece al proyecto seleccionado")

    if project_id is not None:
        project_client_id = (await db.execute(
            select(Project.client_id).where(Project.id == project_id)
        )).scalar_one_or_none()
        if project_client_id is None:
            raise HTTPException(422, "El proyecto seleccionado no existe")
        if client_id is None:
            data["client_id"] = project_client_id
        elif client_id != project_client_id:
            raise HTTPException(422, "El proyecto no pertenece al cliente seleccionado")
    elif phase_id is not None:
        raise HTTPException(422, "Una fase requiere un proyecto")
