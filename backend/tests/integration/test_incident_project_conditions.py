"""Project incident conditions use explicit owners, commitments and real time."""
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import event, select

from backend.db.models import (
    Client,
    Notification,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserPermission,
    UserRole,
)
from backend.services.incident_project_conditions import (
    PROJECT_CLOSING_OVERDUE,
    PROJECT_CLOSING_SOON,
    PROJECT_HOURS_EXCEEDED,
    PROJECT_HOURS_WARNING,
    PROJECT_MONTHLY_HOURS_EXCEEDED,
    PROJECT_MONTHLY_HOURS_WARNING,
    PROJECT_NO_NEXT_ACTION,
    collect_project_conditions,
    project_visibility_clause,
)

NOW = datetime(2026, 9, 20, 10)  # noqa: DTZ001 - application stores naive UTC


async def _owner(db, modules=("projects", "tasks", "timesheet")):
    user = User(
        email=f"project-incidents-{uuid4().hex}@test.local",
        full_name="Project owner",
        hashed_password="test",
        role=UserRole.member,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add_all([
        UserPermission(user_id=user.id, module=module, can_read=True, can_write=False)
        for module in modules
    ])
    await db.flush()
    return user


async def _client(db):
    client = Client(name=f"Incident client {uuid4().hex[:8]}", monthly_budget=1000)
    db.add(client)
    await db.flush()
    return client


async def _project(db, client_id, owner_id, name, **fields):
    status = fields.pop("status", ProjectStatus.active)
    project = Project(
        name=name,
        client_id=client_id,
        owner_id=owner_id,
        status=status,
        **fields,
    )
    db.add(project)
    await db.flush()
    return project


async def test_only_explicit_owner_and_operational_projects_receive_conditions(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    active = await _project(db_session, client.id, owner.id, "Activo")
    planning = await _project(
        db_session, client.id, owner.id, "Planificado",
        status=ProjectStatus.planning,
        target_end_date=NOW + timedelta(days=3),
    )
    for status in (ProjectStatus.completed, ProjectStatus.cancelled, ProjectStatus.on_hold):
        await _project(db_session, client.id, owner.id, status.value, status=status)
    await _project(db_session, client.id, None, "Sin responsable")
    await db_session.flush()

    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    assert any(c.kind == PROJECT_NO_NEXT_ACTION and c.entity_id == active.id for c in conditions.values())
    assert any(c.kind == PROJECT_CLOSING_SOON and c.entity_id == planning.id for c in conditions.values())
    assert {c.entity_id for c in conditions.values()}.issubset({active.id, planning.id})
    assert all(c.href == f"/projects/{c.entity_id}" for c in conditions.values())


async def test_overdue_task_is_a_next_action_but_recurring_template_is_not(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    overdue_project = await _project(db_session, client.id, owner.id, "Con acción atrasada")
    template_project = await _project(db_session, client.id, owner.id, "Sólo plantilla")
    db_session.add_all([
        Task(
            title="Acción atrasada concreta",
            client_id=client.id,
            project_id=overdue_project.id,
            status=TaskStatus.pending,
            due_date=NOW - timedelta(days=4),
            is_recurring=False,
        ),
        Task(
            title="Plantilla recurrente",
            client_id=client.id,
            project_id=template_project.id,
            status=TaskStatus.pending,
            due_date=NOW - timedelta(days=4),
            is_recurring=True,
        ),
    ])
    await db_session.flush()

    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    no_next_ids = {c.entity_id for c in conditions.values() if c.kind == PROJECT_NO_NEXT_ACTION}
    assert overdue_project.id not in no_next_ids
    assert template_project.id in no_next_ids


async def test_hidden_tasks_module_suppresses_no_next_action(db_session, monkeypatch):
    owner = await _owner(db_session)
    client = await _client(db_session)
    await _project(db_session, client.id, owner.id, "Sin módulo tareas")
    from backend.services import incident_project_conditions as project_conditions

    monkeypatch.setattr(
        project_conditions,
        "is_enabled",
        lambda module: module != "tasks",
    )
    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    assert not any(c.kind == PROJECT_NO_NEXT_ACTION for c in conditions.values())


async def test_closing_cycle_changes_only_with_the_explicit_commitment(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(
        db_session, client.id, owner.id, "Cierre contractual",
        target_end_date=NOW - timedelta(days=2),
    )
    first = await collect_project_conditions(db_session, owner.id, NOW)
    closing = next(c for c in first.values() if c.kind == PROJECT_CLOSING_OVERDUE)
    assert closing.severity == "critical"
    assert "2026-09-18" in closing.key

    later = await collect_project_conditions(db_session, owner.id, NOW + timedelta(days=5))
    same = next(c for c in later.values() if c.kind == PROJECT_CLOSING_OVERDUE)
    assert same.key == closing.key
    assert same.fingerprint == closing.fingerprint

    project.target_end_date = NOW + timedelta(days=6)
    await db_session.flush()
    changed = await collect_project_conditions(db_session, owner.id, NOW)
    upcoming = next(c for c in changed.values() if c.kind == PROJECT_CLOSING_SOON)
    assert upcoming.key != closing.key


async def test_month_budget_counts_real_entries_in_business_period_only(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(
        db_session, client.id, owner.id, "Retainer",
        is_recurring=True,
        monthly_hours_budget=10,
    )
    task = Task(
        title="Trabajo real",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        actual_minutes=50_000,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add_all([
        TimeEntry(task_id=task.id, user_id=owner.id, minutes=480, date=datetime(2026, 9, 5)),  # noqa: DTZ001
        TimeEntry(task_id=task.id, user_id=owner.id, minutes=300, date=datetime(2026, 8, 31, 23, 59)),  # noqa: DTZ001
    ])
    await db_session.flush()

    warning = await collect_project_conditions(db_session, owner.id, NOW)
    monthly = next(c for c in warning.values() if c.kind == PROJECT_MONTHLY_HOURS_WARNING)
    assert ":2026-09" in monthly.key
    assert "8h" in monthly.message and "10h" in monthly.message

    db_session.add(TimeEntry(
        task_id=task.id,
        user_id=owner.id,
        minutes=120,
        date=datetime(2026, 9, 20),  # noqa: DTZ001
    ))
    await db_session.flush()
    exceeded = await collect_project_conditions(db_session, owner.id, NOW)
    assert any(c.kind == PROJECT_MONTHLY_HOURS_EXCEEDED for c in exceeded.values())
    assert not any(c.kind == PROJECT_MONTHLY_HOURS_WARNING for c in exceeded.values())


async def test_fixed_budget_uses_real_lifetime_entries_not_task_snapshot(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(
        db_session,
        client.id,
        owner.id,
        "Proyecto puntual",
        pricing_model="project",
        budget_hours=5,
        target_end_date=NOW + timedelta(days=20),
    )
    task = Task(
        title="Trabajo puntual",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        actual_minutes=99_000,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(
        task_id=task.id,
        user_id=owner.id,
        minutes=240,
        date=datetime(2026, 8, 1),  # noqa: DTZ001 - real lifetime entry
    ))
    await db_session.flush()

    warning = await collect_project_conditions(db_session, owner.id, NOW)
    assert any(c.kind == PROJECT_HOURS_WARNING and c.entity_id == project.id for c in warning.values())

    db_session.add(TimeEntry(
        task_id=task.id,
        user_id=owner.id,
        minutes=60,
        date=datetime(2026, 9, 20),  # noqa: DTZ001 - real lifetime entry
    ))
    await db_session.flush()
    exceeded = await collect_project_conditions(db_session, owner.id, NOW)
    assert any(c.kind == PROJECT_HOURS_EXCEEDED and c.entity_id == project.id for c in exceeded.values())
    assert not any(c.kind == PROJECT_HOURS_WARNING and c.entity_id == project.id for c in exceeded.values())


async def test_zero_monthly_ceiling_uses_published_retainer_fallback_in_sql(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(
        db_session,
        client.id,
        owner.id,
        "Retainer con cero explícito",
        is_recurring=True,
        monthly_hours_budget=0,
        budget_hours=10,
    )
    task = Task(title="Horas", client_id=client.id, project_id=project.id)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(
        task_id=task.id,
        user_id=owner.id,
        minutes=480,
        date=datetime(2026, 9, 10),  # noqa: DTZ001 - manual civil date
    ))
    await db_session.flush()

    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    condition = next(c for c in conditions.values() if c.kind == PROJECT_MONTHLY_HOURS_WARNING)
    incident = Notification(
        user_id=owner.id,
        type=condition.kind,
        title=condition.title,
        entity_type="project",
        entity_id=project.id,
        entity_key=str(project.id),
        dedupe_key=condition.key,
        incident_state="active",
        incident_severity="warning",
        incident_revision=1,
        incident_fingerprint=condition.fingerprint,
    )
    db_session.add(incident)
    await db_session.flush()
    assert await db_session.scalar(select(Notification.id).where(
        Notification.id == incident.id,
        project_visibility_clause(owner.id, current_only=True, now=NOW),
    )) == incident.id


async def test_permission_loss_hides_next_action_condition_immediately(db_session):
    owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(db_session, client.id, owner.id, "Permisos frescos")
    condition = next(c for c in (await collect_project_conditions(db_session, owner.id, NOW)).values()
                     if c.kind == PROJECT_NO_NEXT_ACTION)
    incident = Notification(
        user_id=owner.id,
        type=condition.kind,
        title=condition.title,
        entity_type="project",
        entity_id=project.id,
        entity_key=str(project.id),
        dedupe_key=condition.key,
        incident_state="active",
        incident_severity="warning",
        incident_revision=1,
        incident_fingerprint=condition.fingerprint,
    )
    db_session.add(incident)
    await db_session.flush()

    visible = select(Notification.id).where(
        project_visibility_clause(owner.id, current_only=True, now=NOW),
        Notification.id == incident.id,
    )
    assert await db_session.scalar(visible) == incident.id
    permission = (await db_session.execute(select(UserPermission).where(
        UserPermission.user_id == owner.id,
        UserPermission.module == "tasks",
    ))).scalar_one()
    await db_session.delete(permission)
    await db_session.flush()
    assert await db_session.scalar(visible) is None


async def test_history_requires_existing_project_and_current_owner(db_session):
    owner = await _owner(db_session)
    new_owner = await _owner(db_session)
    client = await _client(db_session)
    project = await _project(db_session, client.id, owner.id, "Historia privada")
    condition = next(c for c in (await collect_project_conditions(db_session, owner.id, NOW)).values()
                     if c.kind == PROJECT_NO_NEXT_ACTION)
    incident = Notification(
        user_id=owner.id,
        type=condition.kind,
        title=condition.title,
        entity_type="project",
        entity_id=project.id,
        entity_key=str(project.id),
        dedupe_key=condition.key,
        incident_state="resolved",
        incident_severity="warning",
        incident_revision=2,
        incident_fingerprint=condition.fingerprint,
    )
    db_session.add(incident)
    await db_session.flush()
    historical = select(Notification.id).where(
        Notification.id == incident.id,
        project_visibility_clause(owner.id, current_only=False, now=NOW),
    )
    assert await db_session.scalar(historical) == incident.id

    project.owner_id = new_owner.id
    await db_session.flush()
    assert await db_session.scalar(historical) is None
    await db_session.delete(project)
    await db_session.flush()
    assert await db_session.scalar(historical) is None


async def test_collection_query_count_stays_constant(db_session, engine):
    owner = await _owner(db_session)
    client = await _client(db_session)
    for number in range(35):
        await _project(db_session, client.id, owner.id, f"Proyecto {number}")
    await db_session.flush()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        conditions = await collect_project_conditions(db_session, owner.id, NOW)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert len(conditions) == 35
    assert len(statements) == 1
