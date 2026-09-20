"""Task and timer writes serialize against archived project lifecycle."""
import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.api.routes import time_entries as time_routes
from backend.db.models import (
    Client,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
)
from backend.schemas.time_entry import TimerStartRequest
from backend.services.domain_writes import update_task

pytestmark = pytest.mark.integration


async def _project(db, *, status=ProjectStatus.active):
    client = Client(name=f"Guard client {uuid4().hex[:8]}")
    project = Project(
        name=f"Guard project {uuid4().hex[:8]}", client=client, status=status,
    )
    db.add_all([client, project])
    await db.flush()
    return client, project


async def _task(db, project, user_id, **values):
    data = {
        "title": f"Guard task {uuid4().hex[:8]}",
        "client_id": project.client_id,
        "project_id": project.id,
        "created_by": user_id,
        "status": TaskStatus.pending,
        "priority": TaskPriority.medium,
    }
    data.update(values)
    task = Task(**data)
    db.add(task)
    await db.flush()
    return task


async def test_archived_project_rejects_new_and_moved_operational_tasks(
    admin_client, db_session,
):
    client, archived = await _project(db_session, status=ProjectStatus.completed)
    _other_client, active = await _project(db_session)
    task = await _task(db_session, active, admin_client.test_user.id)

    created = await admin_client.post("/api/tasks", json={
        "title": "No new archived work",
        "client_id": client.id,
        "project_id": archived.id,
    })
    assert created.status_code == 409
    assert "Reabre el proyecto" in created.json()["detail"]

    moved = await admin_client.put(
        f"/api/tasks/{task.id}",
        json={"project_id": archived.id, "client_id": client.id},
    )
    assert moved.status_code == 409
    await db_session.refresh(task)
    assert task.project_id == active.id


async def test_archived_legacy_debt_allows_metadata_and_completion_but_not_reopen(
    admin_client, db_session,
):
    _client, project = await _project(db_session, status=ProjectStatus.cancelled)
    legacy = await _task(db_session, project, admin_client.test_user.id)

    renamed = await admin_client.put(
        f"/api/tasks/{legacy.id}", json={"title": "Corrección histórica"},
    )
    assert renamed.status_code == 200, renamed.text
    completed = await admin_client.put(
        f"/api/tasks/{legacy.id}", json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    reopened = await admin_client.put(
        f"/api/tasks/{legacy.id}", json={"status": "pending"},
    )
    assert reopened.status_code == 409
    assert "Reabre el proyecto" in reopened.json()["detail"]


async def test_archived_project_blocks_restore_template_activation_and_timer(
    admin_client, db_session,
):
    _client, project = await _project(db_session, status=ProjectStatus.completed)
    retired = await _task(
        db_session, project, admin_client.test_user.id,
        retired_at=datetime(2026, 9, 20, 10), retired_reason="Ya no aplica",  # noqa: DTZ001
    )
    paused = await _task(
        db_session, project, admin_client.test_user.id,
        is_recurring=True, recurrence_pattern="weekly", recurrence_day=0,
        recurrence_paused_at=datetime(2026, 9, 20, 10),  # noqa: DTZ001
    )
    timer_target = await _task(db_session, project, admin_client.test_user.id)

    restored = await admin_client.post(f"/api/tasks/{retired.id}/restore", json={
        "expected_updated_at": retired.updated_at.isoformat(),
    })
    assert restored.status_code == 409

    activated = await admin_client.put(
        f"/api/tasks/{paused.id}", json={"recurrence_paused": False},
    )
    assert activated.status_code == 409

    timer = await admin_client.post("/api/timer/start", json={"task_id": timer_target.id})
    assert timer.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(TimeEntry).where(
        TimeEntry.task_id == timer_target.id, TimeEntry.minutes.is_(None),
    )) == 0


async def test_closed_time_correction_remains_allowed_in_archived_project(
    admin_client, db_session,
):
    _client, project = await _project(db_session, status=ProjectStatus.completed)
    task = await _task(
        db_session, project, admin_client.test_user.id, status=TaskStatus.completed,
    )
    entry = TimeEntry(
        task_id=task.id, user_id=admin_client.test_user.id,
        minutes=20, date=datetime(2026, 9, 20), notes="Corrección",  # noqa: DTZ001
    )
    db_session.add(entry)
    await db_session.flush()

    response = await admin_client.put(
        f"/api/time-entries/{entry.id}", json={"minutes": 25},
    )
    assert response.status_code == 200, response.text
    assert response.json()["minutes"] == 25


async def test_timer_revalidates_project_after_autostop_commit(engine, monkeypatch):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        actor = User(
            email=f"timer-guard-{uuid4().hex}@example.test",
            full_name="Timer guard", hashed_password="test", role=UserRole.admin,
            is_active=True, hourly_rate=40, weekly_hours=40,
        )
        setup.add(actor)
        await setup.flush()
        _first_client, first_project = await _project(setup)
        _target_client, target_project = await _project(setup)
        old_task = await _task(setup, first_project, actor.id)
        target = await _task(setup, target_project, actor.id)
        active = TimeEntry(
            task_id=old_task.id, user_id=actor.id, minutes=None,
            started_at=datetime(2026, 9, 21, 8),  # noqa: DTZ001
        )
        setup.add(active)
        await setup.commit()
        actor_id, target_project_id, target_id, active_id = (
            actor.id, target_project.id, target.id, active.id,
        )

    original_lock_tasks = time_routes._lock_tasks
    reacquire_started = asyncio.Event()
    allow_reacquire = asyncio.Event()
    calls = 0

    async def gated_lock_tasks(db, task_ids):
        nonlocal calls
        calls += 1
        if calls == 2:
            reacquire_started.set()
            await allow_reacquire.wait()
        return await original_lock_tasks(db, task_ids)

    monkeypatch.setattr(time_routes, "_lock_tasks", gated_lock_tasks)
    try:
        async with sessions() as request_db, sessions() as archive_db:
            actor = await request_db.get(User, actor_id)
            attempt = asyncio.create_task(time_routes.start_timer(
                TimerStartRequest(task_id=target_id), request_db, actor,
            ))
            await asyncio.wait_for(reacquire_started.wait(), timeout=3)
            await archive_db.execute(
                update(Project).where(Project.id == target_project_id)
                .values(status=ProjectStatus.completed)
            )
            await archive_db.commit()
            allow_reacquire.set()
            with pytest.raises(HTTPException) as blocked:
                await asyncio.wait_for(attempt, timeout=3)
            assert blocked.value.status_code == 409
            await request_db.rollback()

        async with sessions() as verify:
            assert await verify.scalar(select(TimeEntry.minutes).where(TimeEntry.id == active_id)) is not None
            assert await verify.scalar(select(func.count()).select_from(TimeEntry).where(
                TimeEntry.task_id == target_id, TimeEntry.minutes.is_(None),
            )) == 0
    finally:
        allow_reacquire.set()
        async with sessions() as cleanup:
            task_ids = select(Task.id).where(Task.project_id.in_([first_project.id, target_project_id]))
            await cleanup.execute(delete(TimeEntry).where(TimeEntry.task_id.in_(task_ids)))
            await cleanup.execute(delete(Task).where(Task.id.in_(task_ids)))
            await cleanup.execute(delete(Project).where(Project.id.in_([first_project.id, target_project_id])))
            await cleanup.execute(delete(Client).where(Client.id.in_([
                first_project.client_id, target_project.client_id,
            ])))
            await cleanup.execute(delete(User).where(User.id == actor_id))
            await cleanup.commit()


async def test_task_writer_never_waits_behind_project_close_lock(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        actor = User(
            email=f"task-project-lock-{uuid4().hex}@example.test",
            full_name="Task guard", hashed_password="test", role=UserRole.admin,
            is_active=True, hourly_rate=40, weekly_hours=40,
        )
        setup.add(actor)
        await setup.flush()
        client, project = await _project(setup, status=ProjectStatus.completed)
        task = await _task(setup, project, actor.id)
        await setup.commit()
        actor_id, client_id, project_id, task_id = actor.id, client.id, project.id, task.id

    try:
        async with sessions() as close_db, sessions() as writer_db:
            await close_db.execute(
                select(Project.id).where(Project.id == project_id).with_for_update()
            )
            actor = await writer_db.get(User, actor_id)
            stale = await writer_db.get(Task, task_id)
            with pytest.raises(HTTPException) as retry:
                await update_task(writer_db, stale, {"title": "Must roll back"}, actor=actor)
            assert retry.value.status_code == 409
            assert "proyecto está cambiando" in retry.value.detail
            await writer_db.rollback()
            await close_db.rollback()

        async with sessions() as verify:
            assert await verify.scalar(select(Task.title).where(Task.id == task_id)) != "Must roll back"
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Task).where(Task.id == task_id))
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(User).where(User.id == actor_id))
            await cleanup.commit()
