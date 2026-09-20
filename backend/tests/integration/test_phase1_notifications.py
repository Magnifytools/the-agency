"""Periodic notifications retain identity across reads, cycles and concurrent checks."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Notification, Task, TaskStatus, User, UserRole
from backend.services.notification_checks import RETIRED_CHECK_TYPES, NotificationChecks
from backend.services.temporal import business_today


def use_session(monkeypatch, db_session):
    @asynccontextmanager
    async def local_session():
        yield db_session

    monkeypatch.setattr("backend.db.database.async_session", local_session)


async def emit(db, user_id, cycle):
    checks = await NotificationChecks.load(db, user_id)
    if not checks.has("billing_reminder", "project", 123, cycle):
        await checks.create(
            type="billing_reminder",
            entity_type="project",
            entity_id=123,
            title="Revisar facturación",
            message="Condición de prueba",
        )
    await db.commit()


async def test_read_does_not_recreate_check_but_new_cycle_can(db_session, admin_user):
    today = business_today()
    await emit(db_session, admin_user.id, today)
    notification = (await db_session.execute(select(Notification))).scalars().one()
    notification.is_read = True
    await db_session.commit()
    await emit(db_session, admin_user.id, today)
    assert (await db_session.execute(select(func.count(Notification.id)))).scalar() == 1
    await emit(db_session, admin_user.id, today + timedelta(days=31))
    assert (await db_session.execute(select(func.count(Notification.id)))).scalar() == 2


async def test_existing_read_legacy_check_is_adopted(db_session, admin_user):
    legacy = Notification(
        user_id=admin_user.id,
        type="billing_reminder",
        title="Existente",
        entity_type="project",
        entity_id=123,
        is_read=True,
        created_at=datetime.now(),
    )
    db_session.add(legacy)
    await db_session.commit()
    await emit(db_session, admin_user.id, business_today())
    assert legacy.dedupe_key is not None
    assert legacy.is_read is True
    assert (await db_session.execute(select(func.count(Notification.id)))).scalar() == 1


async def test_retired_checks_hidden_without_deleting(
    db_session, admin_user, admin_client
):
    for kind in (*RETIRED_CHECK_TYPES, "task_assigned"):
        db_session.add(Notification(user_id=admin_user.id, type=kind, title=kind))
    await db_session.commit()
    response = await admin_client.get("/api/notifications")
    assert response.status_code == 200
    assert [n["type"] for n in response.json()] == ["task_assigned"]
    assert (await admin_client.get("/api/notifications/unread-count")).json() == {
        "count": 1
    }
    assert (
        await db_session.execute(select(func.count(Notification.id)))
    ).scalar() == len(RETIRED_CHECK_TYPES) + 1


async def test_generate_checks_delegates_to_canonical_incident_without_legacy_duplicate(
    db_session, admin_user, admin_client
):
    task = Task(
        title="Vencida",
        status=TaskStatus.pending,
        assigned_to=admin_user.id,
        due_date=datetime.now() - timedelta(days=2),
    )
    db_session.add(task)
    await db_session.commit()
    first = await admin_client.post("/api/notifications/generate-checks")
    second = await admin_client.post("/api/notifications/generate-checks")
    assert first.status_code == second.status_code == 200
    assert first.json()["created"] == 1
    assert second.json() == {"created": 0, "changed": 0}
    assert (
        await db_session.execute(
            select(func.count(Notification.id)).where(
                Notification.entity_id == task.id,
                Notification.incident_state.is_not(None),
            )
        )
    ).scalar() == 1
    assert (
        await db_session.execute(
            select(func.count(Notification.id)).where(
                Notification.type == "task_overdue",
                Notification.incident_state.is_(None),
            )
        )
    ).scalar() == 0


async def test_concurrent_generators_produce_one_notification(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(
            email="notification-concurrency@test.local",
            full_name="Concurrency",
            hashed_password="unused",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    async def producer():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await emit(db, user_id, business_today())

    try:
        await asyncio.gather(producer(), producer())
        async with AsyncSession(engine) as db:
            count = (
                await db.execute(
                    select(func.count(Notification.id)).where(
                        Notification.user_id == user_id,
                    )
                )
            ).scalar()
            assert count == 1
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(
                delete(Notification).where(Notification.user_id == user_id)
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


async def test_startup_does_not_register_retired_billing_producer(monkeypatch):
    from backend.startup import background_tasks

    monkeypatch.setattr(background_tasks.settings, "INCIDENTS_ENABLED", False)
    monkeypatch.setattr(background_tasks.settings, "DELIVERY_WORKER_ENABLED", False)
    monkeypatch.setattr(background_tasks.settings, "ENGINE_SYNC_ENABLED", False)
    monkeypatch.setattr(background_tasks.settings, "HOLDED_API_KEY", "")
    monkeypatch.setattr(
        background_tasks.settings, "SCHEDULED_COMMUNICATIONS_ENABLED", False
    )
    monkeypatch.setattr(background_tasks.settings, "GOOGLE_CLIENT_ID", "")
    tasks = background_tasks.start_background_tasks()
    try:
        assert "billing-check" not in {task.get_name() for task in tasks}
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_recurrences_keep_project_and_pause_after_close(
    db_session, admin_user, monkeypatch
):
    from backend.db.models import Client, Project, ProjectPhase, ProjectStatus
    from backend.startup.background_tasks import _generate_recurring_instances

    client = Client(name="Recurring client")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Recurring project", client_id=client.id, status=ProjectStatus.active
    )
    db_session.add(project)
    await db_session.flush()
    phase = ProjectPhase(name="Delivery", project_id=project.id)
    db_session.add(phase)
    await db_session.flush()
    template = Task(
        title="Recurring task",
        client_id=client.id,
        project_id=project.id,
        phase_id=phase.id,
        estimated_minutes=45,
        created_by=admin_user.id,
        assigned_to=admin_user.id,
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=business_today().day,
    )
    db_session.add(template)
    await db_session.commit()
    use_session(monkeypatch, db_session)
    await _generate_recurring_instances()
    instance = (
        (
            await db_session.execute(
                select(Task).where(Task.recurring_parent_id == template.id)
            )
        )
        .scalars()
        .one()
    )
    assert (
        instance.project_id,
        instance.phase_id,
        instance.estimated_minutes,
        instance.created_by,
    ) == (
        project.id,
        phase.id,
        45,
        admin_user.id,
    )
    project.status = ProjectStatus.completed
    # Remove only the synthetic instance, allowing another generation if the gate is missing.
    await db_session.delete(instance)
    await db_session.commit()
    await _generate_recurring_instances()
    assert (
        await db_session.execute(
            select(func.count(Task.id)).where(Task.recurring_parent_id == template.id)
        )
    ).scalar() == 0
