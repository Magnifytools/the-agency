"""PostgreSQL contract for explicit project close/reopen decisions."""
import asyncio
from datetime import date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.db.models import (
    ChangeLog,
    Client,
    ClientStatus,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskRecurrenceOccurrence,
    TaskStatus,
    TimeEntry,
    User,
    UserPermission,
    UserRole,
)
from backend.services.project_lifecycle import close_project, get_close_preview
from backend.services.recurrence import generate_recurring_instances

pytestmark = pytest.mark.integration


async def _project(db, user_id: int, *, status=ProjectStatus.active):
    client = Client(name=f"Lifecycle client {uuid4().hex[:8]}")
    project = Project(
        name=f"Lifecycle project {uuid4().hex[:8]}", client=client, status=status,
    )
    db.add_all([client, project])
    await db.flush()
    return client, project


async def _task(db, project: Project, user_id: int, **overrides):
    values = {
        "title": f"Task {uuid4().hex[:8]}", "project_id": project.id,
        "client_id": project.client_id, "created_by": user_id,
        "status": TaskStatus.pending, "priority": TaskPriority.medium,
        "is_recurring": False,
    }
    values.update(overrides)
    task = Task(**values)
    db.add(task)
    await db.flush()
    return task


async def _preview(http, project_id: int, target="completed"):
    response = await http.get(
        f"/api/projects/{project_id}/close-preview", params={"target": target},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_close_preview_reports_exact_blockers_and_permission_aware_samples(
    admin_client, db_session, make_member_client,
):
    _client, project = await _project(db_session, admin_client.test_user.id)
    waiting = await _task(
        db_session, project, admin_client.test_user.id,
        title="Esperando cliente", status=TaskStatus.waiting,
    )
    review = await _task(
        db_session, project, admin_client.test_user.id,
        title="Esperando revisión", status=TaskStatus.in_review,
    )
    completed = await _task(
        db_session, project, admin_client.test_user.id,
        title="Histórica", status=TaskStatus.completed,
    )
    timer = TimeEntry(
        task_id=completed.id, user_id=admin_client.test_user.id,
        minutes=None, started_at=datetime(2026, 9, 21, 8)  # noqa: DTZ001,
    )
    db_session.add(timer)
    await db_session.flush()

    preview = await _preview(admin_client, project.id)
    assert preview["can_close"] is False
    assert preview["blockers"]["active_tasks"]["total"] == 2
    assert {row["id"] for row in preview["blockers"]["active_tasks"]["sample"]} == {waiting.id, review.id}
    assert preview["blockers"]["waiting_count"] == 1
    assert preview["blockers"]["in_review_count"] == 1
    assert preview["blockers"]["active_timers"]["total"] == 1
    assert preview["blockers"]["active_timers"]["sample"][0]["id"] == timer.id

    project_only = await make_member_client([("projects", True, True)])
    try:
        hidden = await _preview(project_only, project.id)
    finally:
        await project_only.aclose()
    assert hidden["blockers"]["active_tasks"]["total"] == 2
    assert hidden["blockers"]["active_tasks"]["sample"] == []
    assert hidden["blockers"]["active_timers"]["total"] == 1
    assert hidden["blockers"]["active_timers"]["sample"] == []


async def test_close_is_reviewed_atomic_and_never_mutates_tasks_or_templates(
    admin_client, db_session,
):
    _client, project = await _project(db_session, admin_client.test_user.id)
    completed = await _task(
        db_session, project, admin_client.test_user.id,
        status=TaskStatus.completed, title="Done",
    )
    template = await _task(
        db_session, project, admin_client.test_user.id,
        status=TaskStatus.pending, title="Template", is_recurring=True,
        recurrence_pattern="weekly", recurrence_day=0,
    )
    preview = await _preview(admin_client, project.id)
    assert preview["can_close"] is True
    assert preview["recurrence"] == {
        "templates": 1, "paused": 0, "suppressed_after_close": 1,
    }

    response = await admin_client.post(f"/api/projects/{project.id}/close", json={
        "target": "completed",
        "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    await db_session.refresh(completed)
    await db_session.refresh(template)
    assert completed.status == TaskStatus.completed
    assert template.status == TaskStatus.pending
    assert template.recurrence_paused_at is None
    journal = (await db_session.execute(
        select(ChangeLog).where(ChangeLog.user_id == admin_client.test_user.id)
        .order_by(ChangeLog.id.desc()).limit(1)
    )).scalar_one()
    assert any(
        operation["entity_type"].lower() == "project"
        and operation["entity_id"] == project.id
        and operation["action"] == "update"
        for operation in journal.operations
    )


async def test_close_rejects_blockers_without_changing_project(admin_client, db_session):
    _client, project = await _project(db_session, admin_client.test_user.id)
    await _task(db_session, project, admin_client.test_user.id)
    preview = await _preview(admin_client, project.id, "cancelled")
    response = await admin_client.post(f"/api/projects/{project.id}/close", json={
        "target": "cancelled", "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_close_blocked"
    assert await db_session.scalar(select(Project.status).where(Project.id == project.id)) == ProjectStatus.active


async def test_blocker_sample_is_bounded_while_total_remains_exact(admin_client, db_session):
    _client, project = await _project(db_session, admin_client.test_user.id)
    for index in range(23):
        await _task(
            db_session, project, admin_client.test_user.id,
            title=f"Open {index:02d}",
        )
    preview = await _preview(admin_client, project.id)
    blockers = preview["blockers"]["active_tasks"]
    assert blockers["total"] == 23
    assert len(blockers["sample"]) == 20
    assert [row["title"] for row in blockers["sample"]] == [
        f"Open {index:02d}" for index in range(20)
    ]


async def test_close_rejects_stale_preview_after_relevant_task_change(admin_client, db_session):
    _client, project = await _project(db_session, admin_client.test_user.id)
    task = await _task(
        db_session, project, admin_client.test_user.id, status=TaskStatus.completed,
    )
    preview = await _preview(admin_client, project.id)
    task.status = TaskStatus.pending
    await db_session.flush()
    response = await admin_client.post(f"/api/projects/{project.id}/close", json={
        "target": "completed", "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "project_close_changed"
    assert body["current_preview"]["blockers"]["active_tasks"]["total"] == 1


async def test_historical_text_and_closed_hours_do_not_invalidate_preview(admin_client, db_session):
    _client, project = await _project(db_session, admin_client.test_user.id)
    task = await _task(
        db_session, project, admin_client.test_user.id,
        status=TaskStatus.completed, title="Original",
    )
    entry = TimeEntry(
        task_id=task.id, user_id=admin_client.test_user.id, minutes=30,
        notes="Original", started_at=datetime(2026, 9, 20, 8)  # noqa: DTZ001,
    )
    db_session.add(entry)
    await db_session.flush()
    preview = await _preview(admin_client, project.id)
    task.title = "Corrected title"
    entry.minutes = 45
    entry.notes = "Corrected note"
    await db_session.flush()
    response = await admin_client.post(f"/api/projects/{project.id}/close", json={
        "target": "completed", "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert response.status_code == 200, response.text


async def test_reopen_preserves_manual_template_pause(admin_client, db_session):
    _client, project = await _project(
        db_session, admin_client.test_user.id, status=ProjectStatus.completed,
    )
    paused = await _task(
        db_session, project, admin_client.test_user.id, is_recurring=True,
        recurrence_pattern="weekly", recurrence_day=1,
        recurrence_paused_at=datetime(2026, 9, 20, 12)  # noqa: DTZ001,
    )
    active = await _task(
        db_session, project, admin_client.test_user.id, is_recurring=True,
        recurrence_pattern="weekly", recurrence_day=2,
    )
    preview_response = await admin_client.get(f"/api/projects/{project.id}/reopen-preview")
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["recurrence"] == {
        "templates": 2, "paused": 1, "suppressed_after_close": 1,
    }
    response = await admin_client.post(f"/api/projects/{project.id}/reopen", json={
        "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    await db_session.refresh(paused)
    await db_session.refresh(active)
    assert paused.recurrence_paused_at is not None
    assert active.recurrence_paused_at is None


async def test_generic_put_requires_explicit_close_and_reopen(admin_client, db_session):
    _client, active = await _project(db_session, admin_client.test_user.id)
    close = await admin_client.put(f"/api/projects/{active.id}", json={"status": "completed"})
    assert close.status_code == 409
    assert close.json()["detail"] == {
        "code": "project_lifecycle_action_required", "action": "close",
    }
    active.status = ProjectStatus.completed
    await db_session.flush()
    reopen = await admin_client.put(f"/api/projects/{active.id}", json={"status": "active"})
    assert reopen.status_code == 409
    assert reopen.json()["detail"] == {
        "code": "project_lifecycle_action_required", "action": "reopen",
    }


async def test_generic_operational_transition_uses_shared_service(admin_client, db_session):
    _client, project = await _project(db_session, admin_client.test_user.id)
    response = await admin_client.put(f"/api/projects/{project.id}", json={"status": "on_hold"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "on_hold"


async def test_generator_winning_advisory_makes_close_recheck_and_refuse(engine):
    """A due child committed ahead of close becomes a blocker, not lost work."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        actor = User(
            email=f"lifecycle-race-{uuid4().hex}@example.test",
            full_name="Race admin", hashed_password="test", role=UserRole.admin,
            is_active=True, hourly_rate=40, weekly_hours=40,
        )
        client = Client(
            name=f"Race client {uuid4().hex[:8]}", status=ClientStatus.active,
        )
        setup.add_all([actor, client])
        await setup.flush()
        project = Project(
            name="Race project", client_id=client.id, status=ProjectStatus.active,
        )
        setup.add(project)
        await setup.flush()
        template = Task(
            title="Monday template", project_id=project.id, client_id=client.id,
            created_by=actor.id, status=TaskStatus.pending,
            priority=TaskPriority.medium, is_recurring=True,
            recurrence_pattern="weekly", recurrence_day=0,
        )
        setup.add(template)
        await setup.commit()
        actor_id, client_id, project_id, template_id = (
            actor.id, client.id, project.id, template.id,
        )

    try:
        async with sessions() as preview_session:
            actor = await preview_session.get(User, actor_id)
            preview = await get_close_preview(
                preview_session, project_id, "completed", actor,
            )
            await preview_session.rollback()

        async with (
            sessions() as generator_db,
            sessions() as close_db,
            sessions() as observer,
        ):
            await generator_db.execute(text("SELECT pg_advisory_xact_lock(76241317)"))
            close_actor = await close_db.get(User, actor_id)
            close_pid = await close_db.scalar(select(func.pg_backend_pid()))
            close_attempt = asyncio.create_task(close_project(
                close_db, project_id, target="completed",
                expected_updated_at=preview.expected_updated_at,
                preview_revision=preview.preview_revision, actor=close_actor,
            ))

            wait_event = None
            for _ in range(100):
                wait_event = await observer.scalar(
                    text("SELECT wait_event FROM pg_stat_activity WHERE pid=:pid"),
                    {"pid": close_pid},
                )
                if wait_event == "advisory":
                    break
                await asyncio.sleep(0)
            assert wait_event == "advisory"

            assert await generate_recurring_instances(
                generator_db, target_date=date(2026, 9, 21),
            ) == 1
            with pytest.raises(HTTPException) as changed:
                await asyncio.wait_for(close_attempt, timeout=3)
            assert changed.value.status_code == 409
            assert changed.value.detail["code"] == "project_close_changed"
            await close_db.rollback()

        async with sessions() as verify:
            assert await verify.scalar(
                select(Project.status).where(Project.id == project_id)
            ) == ProjectStatus.active
            assert await verify.scalar(
                select(func.count()).select_from(Task).where(
                    Task.recurring_parent_id == template_id,
                )
            ) == 1
    finally:
        async with sessions() as cleanup:
            task_ids = select(Task.id).where(Task.project_id == project_id)
            await cleanup.execute(delete(TaskRecurrenceOccurrence).where(
                TaskRecurrenceOccurrence.template_id.in_(task_ids),
            ))
            await cleanup.execute(delete(TimeEntry).where(TimeEntry.task_id.in_(task_ids)))
            await cleanup.execute(delete(Task).where(Task.project_id == project_id))
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(UserPermission).where(UserPermission.user_id == actor_id))
            await cleanup.execute(delete(User).where(User.id == actor_id))
            await cleanup.commit()


async def test_permission_revoked_while_waiting_for_advisory_cannot_close(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        actor = User(
            email=f"lifecycle-permission-{uuid4().hex}@example.test",
            full_name="Project writer", hashed_password="test", role=UserRole.member,
            is_active=True, hourly_rate=40, weekly_hours=40,
        )
        client = Client(name=f"Permission client {uuid4().hex[:8]}")
        setup.add_all([actor, client])
        await setup.flush()
        setup.add(UserPermission(
            user_id=actor.id, module="projects", can_read=True, can_write=True,
        ))
        project = Project(name="Permission race", client_id=client.id)
        setup.add(project)
        await setup.commit()
        actor_id, client_id, project_id = actor.id, client.id, project.id

    try:
        async with sessions() as preview_db:
            preview_actor = await preview_db.get(User, actor_id)
            preview = await get_close_preview(
                preview_db, project_id, "completed", preview_actor,
            )
            await preview_db.rollback()

        async with (
            sessions() as lock_db,
            sessions() as close_db,
            sessions() as permission_db,
            sessions() as observer,
        ):
            await lock_db.execute(text("SELECT pg_advisory_xact_lock(76241317)"))
            close_actor = await close_db.get(User, actor_id)
            close_pid = await close_db.scalar(select(func.pg_backend_pid()))
            close_attempt = asyncio.create_task(close_project(
                close_db, project_id, target="completed",
                expected_updated_at=preview.expected_updated_at,
                preview_revision=preview.preview_revision, actor=close_actor,
            ))
            wait_event = None
            for _ in range(100):
                wait_event = await observer.scalar(
                    text("SELECT wait_event FROM pg_stat_activity WHERE pid=:pid"),
                    {"pid": close_pid},
                )
                if wait_event == "advisory":
                    break
                await asyncio.sleep(0)
            assert wait_event == "advisory"

            await permission_db.execute(update(User).where(User.id == actor_id).values(is_active=False))
            await permission_db.commit()
            await lock_db.commit()
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(close_attempt, timeout=3)
            assert denied.value.status_code == 403
            await close_db.rollback()

        async with sessions() as verify:
            assert await verify.scalar(
                select(Project.status).where(Project.id == project_id)
            ) == ProjectStatus.active
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(UserPermission).where(UserPermission.user_id == actor_id))
            await cleanup.execute(delete(User).where(User.id == actor_id))
            await cleanup.commit()
