# ruff: noqa: DTZ001
"""Regression coverage for digest facts grouped by project."""

from datetime import date, datetime

import pytest
from sqlalchemy import event

from backend.db.models import (
    Client,
    ClientStatus,
    DigestTone,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
)
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_generator import _build_user_prompt

pytestmark = pytest.mark.integration


async def test_digest_groups_all_projects_unassigned_counts_and_period_hours(
    db_session, admin_user
):
    client = Client(name="Cliente multiproyecto", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    project_a = Project(name="Proyecto A", client_id=client.id)
    project_b = Project(name="Proyecto B", client_id=client.id)
    db_session.add_all([project_a, project_b])
    await db_session.flush()

    completed = [
        Task(
            title="Hecho A",
            client_id=client.id,
            project_id=project_a.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 3, 10),
        ),
        Task(
            title="Hecho B",
            client_id=client.id,
            project_id=project_b.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 4, 10),
        ),
        Task(
            title="Hecho cliente",
            client_id=client.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 5, 10),
        ),
    ]
    pending = [
        Task(
            title=f"Pendiente A {index:02d}",
            client_id=client.id,
            project_id=project_a.id,
            status=TaskStatus.pending,
            due_date=datetime(2026, 9, 10 + index),
        )
        for index in range(11)
    ]
    pending.append(
        Task(
            title="Pendiente B visible",
            client_id=client.id,
            project_id=project_b.id,
            status=TaskStatus.pending,
            due_date=datetime(2026, 10, 1),
        )
    )
    db_session.add_all(completed + pending)
    await db_session.flush()
    db_session.add_all(
        [
            TimeEntry(
                task_id=completed[0].id,
                user_id=admin_user.id,
                minutes=30,
                date=datetime(2026, 9, 3),
            ),
            TimeEntry(
                task_id=completed[1].id,
                user_id=admin_user.id,
                minutes=45,
                date=datetime(2026, 9, 4, 10),
                started_at=datetime(2026, 9, 4, 10),
            ),
            TimeEntry(
                task_id=completed[2].id,
                user_id=admin_user.id,
                minutes=15,
                date=datetime(2026, 9, 5),
            ),
            TimeEntry(
                task_id=completed[0].id,
                user_id=admin_user.id,
                minutes=999,
                date=datetime(2026, 9, 8),
            ),
        ]
    )
    await db_session.flush()

    data = await collect_digest_data(
        db_session, client.id, date(2026, 9, 1), date(2026, 9, 7)
    )

    by_name = {group["project_name"]: group for group in data["projects"]}
    assert data["totals"]["pending_total"] == 12
    assert by_name["Proyecto A"]["pending_total"] == 11
    assert len(by_name["Proyecto A"]["pending_tasks"]) == 10
    assert [task["title"] for task in by_name["Proyecto B"]["pending_tasks"]] == [
        "Pendiente B visible"
    ]
    assert by_name["Proyecto A"]["total_minutes"] == 30
    assert by_name["Proyecto B"]["total_minutes"] == 45
    assert data["unassigned"]["total_minutes"] == 15
    assert data["totals"]["total_minutes"] == 90
    assert {
        task["project_name"]
        for group in [*data["projects"], data["unassigned"]]
        for task in group["completed_tasks"]
    } == {
        "Proyecto A",
        "Proyecto B",
        None,
    }
    assert not {"completed_tasks", "in_progress_tasks", "pending_tasks"} & data.keys()
    assert by_name["Proyecto A"]["progress_percent"] == 8
    assert by_name["Proyecto B"]["progress_percent"] == 50

    prompt = _build_user_prompt(data, DigestTone.formal)
    assert "### Proyecto A" in prompt
    assert "### Proyecto B" in prompt
    assert "### Sin proyecto" in prompt
    assert "Tareas pendientes: 12" in prompt
    assert "Pendientes: 11 (muestra 10)" in prompt
    assert "Pendiente B visible" in prompt


def test_digest_prompt_keeps_historical_flat_context_readable():
    prompt = _build_user_prompt(
        {
            "client_name": "Histórico",
            "project_name": "Proyecto antiguo",
            "project_progress": 75,
            "period_start": "2026-08-01",
            "period_end": "2026-08-07",
            "completed_tasks": [{"title": "Hecho histórico"}],
            "in_progress_tasks": [],
            "pending_tasks": [],
            "total_hours": 2,
            "total_minutes": 120,
            "pending_followups": [],
        },
        DigestTone.formal,
    )

    assert "PROYECTO: Proyecto antiguo" in prompt
    assert "Hecho histórico" in prompt


async def test_digest_excludes_recurring_templates_and_separates_unresolved_projects(
    db_session, admin_user
):
    client = Client(name="Cliente destino", status=ClientStatus.active)
    other_client = Client(name="Cliente ajeno", status=ClientStatus.active)
    db_session.add_all([client, other_client])
    await db_session.flush()
    project = Project(name="Proyecto correcto", client_id=client.id)
    foreign_project = Project(name="Proyecto ajeno", client_id=other_client.id)
    db_session.add_all([project, foreign_project])
    await db_session.flush()
    completed = Task(
        title="Trabajo real",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.completed,
        completed_at=datetime(2026, 9, 3, 10),
        is_recurring=False,
    )
    template = Task(
        title="Plantilla semanal",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        is_recurring=True,
    )
    legacy_cross_client = Task(
        title="Referencia histórica ambigua",
        client_id=client.id,
        project_id=foreign_project.id,
        status=TaskStatus.pending,
        is_recurring=False,
    )
    db_session.add_all([completed, template, legacy_cross_client])
    await db_session.flush()
    db_session.add(
        TimeEntry(
            task_id=template.id,
            user_id=admin_user.id,
            minutes=120,
            date=datetime(2026, 9, 3),
        )
    )
    await db_session.flush()

    data = await collect_digest_data(
        db_session, client.id, date(2026, 9, 1), date(2026, 9, 7)
    )

    correct = data["projects"][0]
    assert correct["progress_percent"] == 100
    assert correct["pending_total"] == 0
    assert correct["total_minutes"] == 120
    assert correct["total_hours"] == 2.0
    assert correct["historical_template_minutes"] == 120
    assert data["totals"]["total_minutes"] == 120
    assert data["totals"]["total_hours"] == 2.0
    assert data["totals"]["historical_template_minutes"] == 120
    assert "Plantilla semanal" not in {
        task["title"]
        for group in [
            *data["projects"],
            *data["unresolved_projects"],
            data["unassigned"],
        ]
        for task in group["pending_tasks"]
    }
    assert data["unassigned"]["task_total"] == 0
    assert len(data["unresolved_projects"]) == 1
    unresolved = data["unresolved_projects"][0]
    assert unresolved["project_id"] == foreign_project.id
    assert unresolved["resolution"] == "unresolved"
    assert unresolved["project_name"] == (
        f"Proyecto no resuelto (ID {foreign_project.id})"
    )
    assert unresolved["pending_tasks"][0]["title"] == "Referencia histórica ambigua"

    prompt = _build_user_prompt(data, DigestTone.formal)
    assert "Proyecto no resuelto" in prompt
    assert "### Sin proyecto" not in prompt
    assert "120 minutos reales registrados sobre plantillas históricas" in prompt


async def test_digest_collector_has_fixed_query_budget_bounded_context_and_relevant_history(
    db_session, engine
):
    client = Client(name="Cliente a escala", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    active = Project(name="Proyecto activo", client_id=client.id)
    empty_history = Project(
        name="Histórico vacío",
        client_id=client.id,
        status=ProjectStatus.completed,
    )
    period_history = Project(
        name="Histórico con hecho",
        client_id=client.id,
        status=ProjectStatus.completed,
    )
    db_session.add_all([active, empty_history, period_history])
    await db_session.flush()
    db_session.add_all(
        [
            Task(
                title=f"Pendiente masiva {index:02d}",
                client_id=client.id,
                project_id=active.id,
                status=TaskStatus.pending,
            )
            for index in range(60)
        ]
    )
    db_session.add(
        Task(
            title="Hecho histórico del periodo",
            client_id=client.id,
            project_id=period_history.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 4, 10),
        )
    )
    db_session.add(
        Task(
            title="Pendiente histórica sin hechos",
            client_id=client.id,
            project_id=empty_history.id,
            status=TaskStatus.pending,
        )
    )
    await db_session.flush()

    statements = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        data = await collect_digest_data(
            db_session, client.id, date(2026, 9, 1), date(2026, 9, 7)
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_statement)

    by_name = {group["project_name"]: group for group in data["projects"]}
    assert set(by_name) == {"Proyecto activo", "Histórico con hecho"}
    assert by_name["Proyecto activo"]["pending_total"] == 60
    assert len(by_name["Proyecto activo"]["pending_tasks"]) == 10
    assert by_name["Histórico con hecho"]["completed_total"] == 1
    assert data["totals"]["pending_total"] == 60
    assert not {"completed_tasks", "in_progress_tasks", "pending_tasks"} & data.keys()
    prompt = _build_user_prompt(data, DigestTone.formal)
    assert "TOTALES DEL CONTEXTO INCLUIDO" in prompt
    assert "omiten proyectos históricos sin hechos" in prompt
    assert len(statements) <= 8
    assert not any("task_checklists" in statement for statement in statements)


async def test_digest_hours_include_closed_project_samples_after_cohort_is_known(
    db_session, admin_user
):
    client = Client(name="Cliente histórico con horas", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto cerrado con horas",
        client_id=client.id,
        status=ProjectStatus.cancelled,
    )
    db_session.add(project)
    await db_session.flush()
    completed_outside = Task(
        title="Completada antes del periodo",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.completed,
        completed_at=datetime(2026, 8, 20, 10),
    )
    pending = Task(
        title="Pendiente histórica visible",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
    )
    in_progress = Task(
        title="En curso histórica visible",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.in_progress,
    )
    db_session.add_all([completed_outside, pending, in_progress])
    await db_session.flush()
    db_session.add(
        TimeEntry(
            task_id=completed_outside.id,
            user_id=admin_user.id,
            minutes=45,
            date=datetime(2026, 9, 3),
        )
    )
    await db_session.flush()

    data = await collect_digest_data(
        db_session, client.id, date(2026, 9, 1), date(2026, 9, 7)
    )

    assert len(data["projects"]) == 1
    group = data["projects"][0]
    assert group["project_name"] == "Proyecto cerrado con horas"
    assert group["task_total"] == 3
    assert group["completed_total"] == 0
    assert group["pending_total"] == 1
    assert group["in_progress_total"] == 1
    assert group["total_minutes"] == 45
    assert [task["title"] for task in group["pending_tasks"]] == [
        "Pendiente histórica visible"
    ]
    assert [task["title"] for task in group["in_progress_tasks"]] == [
        "En curso histórica visible"
    ]
    assert group["completed_tasks"] == []
    assert data["totals"]["task_total"] == 3
    assert data["totals"]["pending_total"] == 1
    assert data["totals"]["in_progress_total"] == 1
