"""Phase 1 regressions for task scope, agenda, actual time and dailys."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.tasks import update_task
from backend.db.models import (
    Client,
    Project,
    ProjectPhase,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
)
from backend.schemas.task import TaskUpdate


async def _task(db_session, user_id: int, **overrides) -> Task:
    data = {
        "title": "Tarea de prueba",
        "status": TaskStatus.pending,
        "assigned_to": user_id,
        "created_by": user_id,
        "is_recurring": False,
    }
    data.update(overrides)
    task = Task(**data)
    db_session.add(task)
    await db_session.flush()
    return task


@pytest.mark.asyncio
async def test_saving_same_actual_minutes_does_not_duplicate_null_notes_timer(
    admin_client, db_session
):
    task = await _task(db_session, admin_client.test_user.id, actual_minutes=60)
    original_date = datetime(2026, 8, 5, 11, 30)
    db_session.add(TimeEntry(
        task_id=task.id,
        user_id=admin_client.test_user.id,
        minutes=60,
        date=original_date,
        notes=None,
    ))
    await db_session.flush()

    response = await admin_client.put(
        f"/api/tasks/{task.id}",
        json={"title": "Solo cambia el título", "actual_minutes": 60},
    )
    assert response.status_code == 200, response.text

    entries = (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == task.id)
    )).scalars().all()
    assert [(entry.minutes, entry.notes, entry.date) for entry in entries] == [
        (60, None, original_date)
    ]


@pytest.mark.asyncio
async def test_explicit_actual_edit_preserves_other_users_and_manual_date(
    admin_client, member_user, db_session
):
    actor_id = admin_client.test_user.id
    task = await _task(db_session, actor_id, actual_minutes=60)
    historical_date = datetime(2026, 7, 10, 9, 0)
    db_session.add_all([
        TimeEntry(task_id=task.id, user_id=actor_id, minutes=30, date=historical_date, notes="[manual]"),
        TimeEntry(task_id=task.id, user_id=member_user.id, minutes=20, date=datetime(2026, 7, 11), notes="[manual]"),
        TimeEntry(task_id=task.id, user_id=actor_id, minutes=10, date=datetime(2026, 7, 12), notes=None),
    ])
    await db_session.flush()

    response = await admin_client.put(
        f"/api/tasks/{task.id}", json={"actual_minutes": 100}
    )
    assert response.status_code == 200, response.text

    entries = (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == task.id).order_by(TimeEntry.id)
    )).scalars().all()
    assert entries[0].user_id == actor_id
    assert entries[0].minutes == 70
    assert entries[0].date == historical_date
    assert entries[1].user_id == member_user.id
    assert entries[1].minutes == 20
    assert entries[2].minutes == 10


@pytest.mark.asyncio
async def test_concurrent_explicit_totals_create_one_manual_adjustment(engine):
    """The Task row lock serializes retries and edits from different actors."""
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        first_user = User(
            email="phase1-time-first@test.local",
            full_name="Time First",
            hashed_password="unused",
            role=UserRole.admin,
            is_active=True,
        )
        second_user = User(
            email="phase1-time-second@test.local",
            full_name="Time Second",
            hashed_password="unused",
            role=UserRole.admin,
            is_active=True,
        )
        setup.add_all([first_user, second_user])
        await setup.flush()
        task = Task(
            title="Concurrent total",
            status=TaskStatus.pending,
            assigned_to=first_user.id,
            created_by=first_user.id,
            is_recurring=False,
        )
        setup.add(task)
        await setup.commit()
        task_id = task.id
        first_user_id = first_user.id
        second_user_id = second_user.id

    async def set_total(user_id: int):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            user = await session.get(User, user_id)
            return await update_task(
                task_id,
                TaskUpdate(actual_minutes=60),
                db=session,
                current_user=user,
            )

    try:
        first, second = await asyncio.gather(
            set_total(first_user_id),
            set_total(second_user_id),
        )
        assert first.actual_minutes == 60
        assert second.actual_minutes == 60
        async with AsyncSession(engine) as verify:
            task_actual = (await verify.execute(
                select(Task.actual_minutes).where(Task.id == task_id)
            )).scalar_one()
            entries = (await verify.execute(
                select(TimeEntry).where(TimeEntry.task_id == task_id)
            )).scalars().all()
            assert task_actual == 60
            assert sum(entry.minutes or 0 for entry in entries) == 60
            assert len(entries) == 1
            assert entries[0].user_id in {first_user_id, second_user_id}
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(TimeEntry).where(TimeEntry.task_id == task_id))
            await cleanup.execute(delete(Task).where(Task.id == task_id))
            await cleanup.execute(delete(User).where(User.id.in_([first_user_id, second_user_id])))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_create_preserves_nulls_and_validates_project_hierarchy(
    admin_client, db_session
):
    client_a = Client(name="Cliente A")
    client_b = Client(name="Cliente B")
    db_session.add_all([client_a, client_b])
    await db_session.flush()
    project = Project(name="Proyecto A", client_id=client_a.id)
    db_session.add(project)
    await db_session.flush()
    phase = ProjectPhase(name="Fase A", project_id=project.id)
    db_session.add(phase)
    await db_session.flush()

    inferred = await admin_client.post(
        "/api/tasks", json={"title": "Con fase", "phase_id": phase.id}
    )
    assert inferred.status_code == 201, inferred.text
    assert inferred.json()["project_id"] == project.id
    assert inferred.json()["client_id"] == client_a.id
    assert inferred.json()["assigned_to"] is None
    assert inferred.json()["scheduled_date"] is None

    conflict = await admin_client.post(
        "/api/tasks",
        json={"title": "Incoherente", "project_id": project.id, "client_id": client_b.id},
    )
    assert conflict.status_code == 422
    assert "no pertenece" in conflict.json()["detail"]


@pytest.mark.asyncio
async def test_agenda_is_server_filtered_paginated_and_timezone_aware(
    admin_client, db_session
):
    user_id = admin_client.test_user.id
    target_day = date(2026, 9, 17)
    for index in range(26):
        await _task(
            db_session,
            user_id,
            title=f"Arrastre {index:02d}",
            scheduled_date=target_day - timedelta(days=1),
        )
    await _task(
        db_session,
        user_id,
        title="La única de hoy",
        scheduled_date=target_day,
    )
    await _task(
        db_session,
        user_id,
        title="Vencida aunque replanificada",
        scheduled_date=target_day + timedelta(days=3),
        due_date=datetime(2026, 9, 16, 12, 0),
    )
    await _task(
        db_session,
        user_id,
        title="Completada dentro del día Madrid",
        status=TaskStatus.completed,
        completed_at=datetime(2026, 9, 16, 22, 30),
    )
    await _task(
        db_session,
        user_id,
        title="Completada fuera del día Madrid",
        status=TaskStatus.completed,
        completed_at=datetime(2026, 9, 17, 22, 30),
    )
    await db_session.flush()

    first = await admin_client.get(
        "/api/tasks/agenda",
        params={"date": target_day.isoformat(), "section": "planned", "page": 1, "page_size": 25},
    )
    carryover_first = await admin_client.get(
        "/api/tasks/agenda",
        params={"date": target_day.isoformat(), "section": "carryover", "page": 1, "page_size": 25},
    )
    carryover_second = await admin_client.get(
        "/api/tasks/agenda",
        params={"date": target_day.isoformat(), "section": "carryover", "page": 2, "page_size": 25},
    )
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 1
    assert [item["title"] for item in first.json()["items"]] == ["La única de hoy"]
    assert carryover_first.json()["total"] == 27
    assert len(carryover_first.json()["items"]) == 25
    assert len(carryover_second.json()["items"]) == 2
    assert "Vencida aunque replanificada" in {
        item["title"]
        for item in carryover_first.json()["items"] + carryover_second.json()["items"]
    }

    completed = await admin_client.get(
        "/api/tasks/agenda",
        params={
            "date": target_day.isoformat(),
            "section": "completed",
            "timezone_offset_minutes": -120,
        },
    )
    assert completed.status_code == 200, completed.text
    assert [item["title"] for item in completed.json()["items"]] == [
        "Completada dentro del día Madrid"
    ]


@pytest.mark.asyncio
async def test_daily_parse_never_creates_estimated_or_fallback_time(
    admin_client, db_session, monkeypatch
):
    from backend.api.routes import dailys as dailys_route

    task = await _task(
        db_session,
        admin_client.test_user.id,
        title="Auditoría técnica",
        estimated_minutes=90,
    )

    async def _parsed(_raw_text):
        return {
            "projects": [],
            "general": [{"description": task.title, "details": ""}],
            "tomorrow": [],
        }

    monkeypatch.setattr(dailys_route, "parse_daily_update", _parsed)
    response = await admin_client.post(
        "/api/dailys",
        json={"raw_text": "He terminado la auditoría"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["time_entries_created"] == 0
    count = (await db_session.execute(
        select(func.count()).select_from(TimeEntry).where(TimeEntry.task_id == task.id)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_status_transition_sets_and_clears_completed_at(admin_client, db_session):
    task = await _task(db_session, admin_client.test_user.id)

    completed = await admin_client.put(
        f"/api/tasks/{task.id}", json={"status": "completed"}
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_at"] is not None

    reopened = await admin_client.put(
        f"/api/tasks/{task.id}", json={"status": "pending"}
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_create_completed_and_explicit_actual_are_real_events(
    admin_client, db_session
):
    response = await admin_client.post(
        "/api/tasks",
        json={"title": "Ya realizada", "status": "completed", "actual_minutes": 45},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["completed_at"] is not None
    entry = (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == payload["id"])
    )).scalar_one()
    assert entry.user_id == admin_client.test_user.id
    assert entry.minutes == 45
    assert entry.notes == "[manual]"


@pytest.mark.asyncio
async def test_explicit_actual_requires_timesheet_write_permission(
    make_member_client, db_session
):
    tasks_only = await make_member_client([("tasks", True, True)])
    try:
        plain = await tasks_only.post("/api/tasks", json={"title": "Sin horas"})
        assert plain.status_code == 201, plain.text
        denied = await tasks_only.post(
            "/api/tasks", json={"title": "Con horas", "actual_minutes": 15}
        )
        assert denied.status_code == 403
        same_value = await tasks_only.put(
            f"/api/tasks/{plain.json()['id']}", json={"actual_minutes": None}
        )
        assert same_value.status_code == 200, same_value.text
    finally:
        await tasks_only.aclose()

    allowed_client = await make_member_client([
        ("tasks", True, True), ("timesheet", True, True),
    ])
    try:
        allowed = await allowed_client.post(
            "/api/tasks", json={"title": "Con permiso", "actual_minutes": 15}
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await allowed_client.aclose()
