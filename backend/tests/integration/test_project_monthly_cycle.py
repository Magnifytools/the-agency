"""Recurring project cycles use project-scoped, civil-month facts."""
from datetime import date, datetime

import pytest
from sqlalchemy import event

from backend.db.models import (
    Client,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
)
from backend.services.project_cycles import collect_project_monthly_cycle

pytestmark = pytest.mark.integration


async def test_monthly_cycle_isolates_project_and_keeps_activity_populations_distinct(
    admin_client, admin_user, db_session
):
    client = Client(name="Cliente con dos retainers")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Retainer A",
        client_id=client.id,
        status=ProjectStatus.active,
        is_recurring=True,
        budget_hours=10,
    )
    other = Project(
        name="Retainer B",
        client_id=client.id,
        status=ProjectStatus.active,
        is_recurring=True,
        budget_hours=20,
    )
    db_session.add_all([project, other])
    await db_session.flush()
    planned = Task(
        title="Plan de septiembre",
        project_id=project.id,
        client_id=client.id,
        status=TaskStatus.pending,
        scheduled_date=date(2026, 9, 10),
    )
    completed = Task(
        title="Finalizada en septiembre",
        project_id=project.id,
        client_id=client.id,
        status=TaskStatus.completed,
        scheduled_date=date(2026, 8, 28),
        completed_at=datetime(2026, 9, 15, 9),  # noqa: DTZ001
    )
    template = Task(
        title="Plantilla mensual",
        project_id=project.id,
        client_id=client.id,
        is_recurring=True,
        scheduled_date=date(2026, 9, 1),
    )
    foreign = Task(
        title="Mismo cliente, otro proyecto",
        project_id=other.id,
        client_id=client.id,
        scheduled_date=date(2026, 9, 12),
    )
    db_session.add_all([planned, completed, template, foreign])
    midnight_completion = Task(
        title="Finalizada al empezar septiembre en Madrid",
        project_id=project.id,
        client_id=client.id,
        status=TaskStatus.completed,
        completed_at=datetime(2026, 8, 31, 22, 30),  # noqa: DTZ001
    )
    unknown_completion = Task(
        title="Histórica sin fecha real",
        project_id=project.id,
        client_id=client.id,
        status=TaskStatus.completed,
        completed_at=None,
    )
    db_session.add_all([midnight_completion, unknown_completion])
    await db_session.flush()
    db_session.add_all(
        [
            TimeEntry(
                task_id=planned.id,
                user_id=admin_user.id,
                minutes=90,
                date=datetime(2026, 9, 10),  # noqa: DTZ001
            ),
            TimeEntry(
                task_id=planned.id,
                user_id=admin_user.id,
                minutes=30,
                date=datetime(2026, 8, 31, 22),  # noqa: DTZ001
                started_at=datetime(2026, 8, 31, 22),  # noqa: DTZ001
            ),
            TimeEntry(
                task_id=planned.id,
                user_id=admin_user.id,
                minutes=999,
                date=datetime(2026, 8, 31, 23),  # noqa: DTZ001
                started_at=None,
            ),
            TimeEntry(
                task_id=foreign.id,
                user_id=admin_user.id,
                minutes=600,
                date=datetime(2026, 9, 10),  # noqa: DTZ001
            ),
        ]
    )
    await db_session.flush()

    project_tasks = await admin_client.get(f"/api/projects/{project.id}/tasks")
    assert project_tasks.status_code == 200, project_tasks.text
    serialized = [
        task
        for group in project_tasks.json()["phases"]
        for task in group["tasks"]
    ] + project_tasks.json()["unassigned_tasks"]
    assert next(task for task in serialized if task["id"] == template.id)["is_recurring"] is True

    response = await admin_client.get(
        f"/api/projects/{project.id}/monthly-cycle", params={"month": "2026-09"}
    )

    assert response.status_code == 200, response.text
    cycle = response.json()
    assert cycle["month"] == "2026-09"
    assert cycle["planned_count"] == 1
    assert cycle["completed_in_month_count"] == 2
    assert cycle["total_minutes"] == 120
    assert cycle["used_hours"] == 2
    assert cycle["budget_hours"] == 10
    assert cycle["remaining_hours"] == 8
    assert {task["id"] for task in cycle["tasks"]} == {
        planned.id,
        completed.id,
        midnight_completion.id,
    }

    unsupported = await admin_client.get(
        f"/api/projects/{project.id}/monthly-cycle", params={"month": "9999-12"}
    )
    assert unsupported.status_code == 422


async def test_monthly_cycle_does_not_change_one_off_project_contract(
    admin_client, db_session
):
    client = Client(name="Cliente puntual")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto puntual",
        client_id=client.id,
        status=ProjectStatus.active,
        is_recurring=False,
    )
    db_session.add(project)
    await db_session.flush()

    response = await admin_client.get(
        f"/api/projects/{project.id}/monthly-cycle", params={"month": "2026-09"}
    )

    assert response.status_code == 409


async def test_monthly_cycle_returns_large_month_in_constant_queries(
    db_session, admin_user, engine
):
    client = Client(name="Cliente volumen mensual")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Retainer volumen",
        client_id=client.id,
        status=ProjectStatus.active,
        is_recurring=True,
    )
    db_session.add(project)
    await db_session.flush()
    tasks = [
        Task(
            title=f"Tarea mensual {index}",
            project_id=project.id,
            client_id=client.id,
            scheduled_date=date(2026, 9, (index % 28) + 1),
        )
        for index in range(1001)
    ]
    db_session.add_all(tasks)
    await db_session.flush()
    db_session.add_all(
        [
            TimeEntry(
                task_id=task.id,
                user_id=admin_user.id,
                minutes=1,
                date=datetime(2026, 9, 10),  # noqa: DTZ001
            )
            for task in tasks
        ]
    )
    await db_session.flush()
    db_session.expunge(project)
    statements = 0

    def count(*_args):
        nonlocal statements
        statements += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        cycle = await collect_project_monthly_cycle(db_session, project.id, "2026-09")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert statements == 3
    assert cycle is not None
    assert len(cycle["tasks"]) == cycle["planned_count"] == 1001
    assert cycle["total_minutes"] == 1001


async def test_monthly_cycle_follows_current_projects_read_permission(
    db_session, make_member_client
):
    member = await make_member_client([("projects", True, False)])
    try:
        client = Client(name="Cliente permisos ciclo")
        db_session.add(client)
        await db_session.flush()
        project = Project(
            name="Retainer permisos",
            client_id=client.id,
            status=ProjectStatus.active,
            is_recurring=True,
        )
        db_session.add(project)
        await db_session.commit()

        allowed = await member.get(
            f"/api/projects/{project.id}/monthly-cycle",
            params={"month": "2026-09"},
        )
        assert allowed.status_code == 200
        permission = next(
            item for item in member.test_user.permissions if item.module == "projects"
        )
        permission.can_read = False
        await db_session.commit()
        denied = await member.get(
            f"/api/projects/{project.id}/monthly-cycle",
            params={"month": "2026-09"},
        )
        assert denied.status_code == 403
    finally:
        await member.aclose()
