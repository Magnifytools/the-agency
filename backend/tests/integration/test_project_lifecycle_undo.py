"""Undo obeys the same project lifecycle boundary as public task writers."""
import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.changes import undo_change
from backend.core.security import hash_password
from backend.db.models import (
    ChangeLog,
    Client,
    ClientStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    User,
    UserRole,
)
from backend.services import change_journal

pytestmark = pytest.mark.asyncio


async def _project(db_session, *, status=ProjectStatus.active):
    client = Client(name="Lifecycle undo", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Lifecycle undo", client_id=client.id, status=status)
    db_session.add(project)
    await db_session.commit()
    return project


async def _project_status_change(db_session, admin_user, project, *, before, after):
    change = ChangeLog(
        user_id=admin_user.id,
        entity_type="project",
        entity_id=project.id,
        action="update",
        label="Estado del proyecto",
        operations=[{
            "entity_type": "project", "entity_id": project.id,
            "action": "update", "name": project.name,
            "before": {"status": before}, "after": {"status": after},
        }],
    )
    db_session.add(change)
    await db_session.commit()
    return change


async def _deleted_task_change(admin_client, db_session, task):
    response = await admin_client.delete(f"/api/tasks/{task.id}")
    assert response.status_code == 204, response.text
    return (await db_session.scalars(
        select(ChangeLog).where(
            ChangeLog.entity_type == "task", ChangeLog.entity_id == task.id,
        ).order_by(ChangeLog.id.desc()).limit(1)
    )).one()


async def test_undo_reopen_refuses_to_archive_project_with_new_active_work(
    admin_client, db_session, admin_user,
):
    """The inverse uses current blockers and rolls its status write back."""
    project = await _project(db_session)
    project_id = project.id
    change = await _project_status_change(
        db_session, admin_user, project, before="completed", after="active",
    )
    change_id = change.id
    db_session.add(Task(title="Trabajo posterior", project_id=project.id))
    await db_session.commit()

    response = await admin_client.post(f"/api/changes/{change_id}/undo")

    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).status == ProjectStatus.active
    assert (await db_session.get(ChangeLog, change_id)).undone_at is None


async def test_undo_close_reopens_without_reactivating_paused_template(
    admin_client, db_session, admin_user,
):
    project = await _project(db_session, status=ProjectStatus.completed)
    project_id = project.id
    paused_at = datetime(2026, 9, 21, 8, 30)  # noqa: DTZ001 - DB civil timestamp
    template = Task(
        title="Plantilla pausada", project_id=project.id, is_recurring=True,
        recurrence_pattern="weekly", recurrence_paused_at=paused_at,
    )
    db_session.add(template)
    await db_session.commit()
    template_id = template.id
    change = await _project_status_change(
        db_session, admin_user, project, before="active", after="completed",
    )

    response = await admin_client.post(f"/api/changes/{change.id}/undo")

    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).status == ProjectStatus.active
    assert (await db_session.get(Task, template_id)).recurrence_paused_at == paused_at


@pytest.mark.parametrize("historical", ["completed", "retired", "paused_template"])
async def test_deleted_historical_task_can_be_restored_inside_archived_project(
    admin_client, db_session, historical,
):
    project = await _project(db_session)
    values = {"title": f"Histórica {historical}", "project_id": project.id}
    if historical == "completed":
        values["status"] = TaskStatus.completed
    elif historical == "retired":
        values.update(
            retired_at=datetime(2026, 9, 20, 9),  # noqa: DTZ001 - DB civil timestamp
            retired_reason="Histórica",
        )
    else:
        values.update(
            is_recurring=True, recurrence_pattern="weekly",
            recurrence_paused_at=datetime(2026, 9, 20, 9),  # noqa: DTZ001 - DB civil timestamp
        )
    task = Task(**values)
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    change = await _deleted_task_change(admin_client, db_session, task)
    with change_journal.paused():
        project.status = ProjectStatus.completed
        await db_session.commit()

    response = await admin_client.post(f"/api/changes/{change.id}/undo")

    assert response.status_code == 200, response.text
    db_session.expire_all()
    restored = await db_session.get(Task, task_id)
    assert restored is not None
    assert (
        restored.status == TaskStatus.completed
        or restored.retired_at is not None
        or restored.recurrence_paused_at is not None
    )


async def test_deleted_active_task_cannot_be_restored_inside_archived_project(
    admin_client, db_session,
):
    project = await _project(db_session)
    task = Task(title="Trabajo operativo", project_id=project.id)
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    change = await _deleted_task_change(admin_client, db_session, task)
    change_id = change.id
    with change_journal.paused():
        project.status = ProjectStatus.completed
        await db_session.commit()

    response = await admin_client.post(f"/api/changes/{change.id}/undo")

    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert await db_session.get(Task, task_id) is None
    assert (await db_session.get(ChangeLog, change_id)).undone_at is None


async def test_completed_template_cannot_be_unpaused_inside_archived_project(
    admin_client, db_session,
):
    project = await _project(db_session, status=ProjectStatus.completed)
    template = Task(
        title="Completed is still a template", project_id=project.id,
        status=TaskStatus.completed, is_recurring=True,
        recurrence_pattern="weekly", recurrence_day=0,
        recurrence_paused_at=datetime(2026, 9, 20, 9),  # noqa: DTZ001
    )
    db_session.add(template)
    await db_session.commit()

    response = await admin_client.put(
        f"/api/tasks/{template.id}", json={"recurrence_paused": False},
    )

    assert response.status_code == 409, response.text
    await db_session.refresh(template)
    assert template.recurrence_paused_at is not None


async def test_undo_cannot_restore_completed_unpaused_template_into_archive(
    admin_client, db_session,
):
    project = await _project(db_session)
    template = Task(
        title="Completed unpaused template", project_id=project.id,
        status=TaskStatus.completed, is_recurring=True,
        recurrence_pattern="weekly", recurrence_day=0,
    )
    db_session.add(template)
    await db_session.commit()
    template_id = template.id
    change = await _deleted_task_change(admin_client, db_session, template)
    change_id = change.id
    with change_journal.paused():
        project.status = ProjectStatus.completed
        await db_session.commit()

    response = await admin_client.post(f"/api/changes/{change_id}/undo")

    assert response.status_code == 409, response.text
    db_session.expire_all()
    assert await db_session.get(Task, template_id) is None
    assert (await db_session.get(ChangeLog, change_id)).undone_at is None


async def test_conflict_skipped_project_status_validates_actual_result(
    admin_client, db_session, admin_user,
):
    project = await _project(db_session, status=ProjectStatus.planning)
    project_id = project.id
    change = await _project_status_change(
        db_session, admin_user, project, before="completed", after="active",
    )

    response = await admin_client.post(f"/api/changes/{change.id}/undo")

    assert response.status_code == 200, response.text
    assert any("status" in warning for warning in response.json()["warnings"])
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).status == ProjectStatus.planning


async def test_undo_waits_for_lifecycle_writer_then_revalidates_new_work(
    engine, monkeypatch,
):
    """The shared advisory boundary prevents a close decision on a stale set."""
    from backend.services import project_lifecycle

    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email=f"lifecycle-undo-{uuid4()}@test.local", full_name="Undo lifecycle",
            hashed_password=hash_password("unused"), role=UserRole.admin, is_active=True,
        )
        setup.add(actor)
        await setup.flush()
        project = await _project(setup)
        project_id = project.id
        change = await _project_status_change(
            setup, actor, project, before="completed", after="active",
        )
        change_id, actor_id = change.id, actor.id
    reached_lock = asyncio.Event()
    original_lock = project_lifecycle.acquire_project_lifecycle_lock

    async def observed_lock(session):
        reached_lock.set()
        await original_lock(session)

    monkeypatch.setattr(project_lifecycle, "acquire_project_lifecycle_lock", observed_lock)
    async with AsyncSession(engine, expire_on_commit=False) as writer, AsyncSession(
        engine, expire_on_commit=False,
    ) as undo_session:
        await original_lock(writer)
        actor = await undo_session.get(User, actor_id)
        pending = asyncio.create_task(undo_change(change_id, undo_session, actor))
        await asyncio.wait_for(reached_lock.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not pending.done()
        writer.add(Task(title="Creada durante la espera", project_id=project_id))
        await writer.commit()
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(pending, timeout=2)

    assert error.value.status_code == 409
    async with AsyncSession(engine) as verifier:
        assert (await verifier.get(Project, project_id)).status == ProjectStatus.active
        assert (await verifier.get(ChangeLog, change_id)).undone_at is None
