"""Every task/project writer preserves the client-project-phase hierarchy."""

from contextlib import asynccontextmanager
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.db.models import (
    Client,
    ClientStatus,
    GrowthIdea,
    Project,
    ProjectPhase,
    ProjectStatus,
    ProjectTemplateDB,
    Task,
    TaskStatus,
)


pytestmark = pytest.mark.integration


@pytest.fixture
async def scope_clients(db_session):
    first = Client(name=f"Scope A {uuid4().hex[:6]}", status=ClientStatus.active)
    second = Client(name=f"Scope B {uuid4().hex[:6]}", status=ClientStatus.active)
    db_session.add_all([first, second])
    await db_session.flush()
    return first, second


async def test_unscoped_internal_task_stays_valid_but_dangling_client_is_controlled(
    admin_client,
):
    internal = await admin_client.post("/api/tasks", json={"title": "Trabajo interno"})
    assert internal.status_code == 201, internal.text
    assert internal.json()["client_id"] is None
    assert internal.json()["project_id"] is None

    dangling = await admin_client.post(
        "/api/tasks", json={"title": "Cliente inexistente", "client_id": 2_000_000_000}
    )
    assert dangling.status_code == 422, dangling.text
    assert "cliente" in dangling.json()["detail"].lower()


async def test_project_writers_reject_dangling_clients_without_fk_500(admin_client):
    missing_client = 2_000_000_000
    manual = await admin_client.post(
        "/api/projects", json={"name": "Proyecto huérfano", "client_id": missing_client}
    )
    assert manual.status_code == 422, manual.text

    template = await admin_client.post(
        "/api/projects/from-template",
        params={"client_id": missing_client, "template_key": "cualquiera"},
    )
    assert template.status_code == 422, template.text


async def test_template_tasks_are_created_with_one_coherent_scope(
    admin_client, db_session, scope_clients
):
    client, _ = scope_clients
    key = f"scope_{uuid4().hex}"
    db_session.add(ProjectTemplateDB(
        key=key,
        name="Plantilla coherente",
        phases=[{"name": "Entrega", "default_days": 3}],
        default_tasks=[{"phase": 0, "title": "Preparar entrega", "minutes": 30}],
        created_by=admin_client.test_user.id,
    ))
    await db_session.flush()

    response = await admin_client.post(
        "/api/projects/from-template",
        params={"client_id": client.id, "template_key": key},
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    task = (await db_session.execute(
        select(Task).where(Task.project_id == project_id)
    )).scalars().one()
    phase = await db_session.get(ProjectPhase, task.phase_id)
    assert task.client_id == client.id
    assert phase.project_id == project_id


async def test_update_and_bulk_cannot_cross_a_task_into_another_client(
    admin_client, db_session, scope_clients
):
    first, second = scope_clients
    project = Project(name="Proyecto del primero", client_id=first.id)
    db_session.add(project)
    await db_session.flush()
    task = Task(
        title="Scope estable",
        client_id=first.id,
        project_id=project.id,
        status=TaskStatus.pending,
        created_by=admin_client.test_user.id,
    )
    db_session.add(task)
    await db_session.flush()

    single = await admin_client.put(
        f"/api/tasks/{task.id}", json={"client_id": second.id}
    )
    assert single.status_code == 422, single.text

    bulk = await admin_client.patch(
        "/api/tasks/bulk/update",
        json={"ids": [task.id], "updates": {"client_id": second.id}},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["updated"] == 0
    assert bulk.json()["failed"] == bulk.json()["requested"] == 1
    assert bulk.json()["results"][0]["updated"] is False
    assert bulk.json()["results"][0]["id"] == task.id
    await db_session.refresh(task)
    assert (task.client_id, task.project_id) == (first.id, project.id)


async def test_growth_conversions_reject_unknown_client(admin_client, db_session):
    idea = GrowthIdea(title="Idea sin cliente válido")
    db_session.add(idea)
    await db_session.flush()

    for path in ("convert-to-project", "create-task"):
        response = await admin_client.post(
            f"/api/growth/{idea.id}/{path}", params={"client_id": 2_000_000_000}
        )
        assert response.status_code == 422, response.text

    await db_session.refresh(idea)
    assert idea.project_id is None
    assert idea.task_id is None


async def test_recurrence_skips_legacy_cross_client_scope(
    db_session, admin_user, scope_clients, monkeypatch
):
    from backend.startup.background_tasks import _generate_recurring_instances

    first, second = scope_clients
    project = Project(name="Proyecto A", client_id=first.id, status=ProjectStatus.active)
    db_session.add(project)
    await db_session.flush()
    phase = ProjectPhase(name="Fase A", project_id=project.id)
    db_session.add(phase)
    await db_session.flush()
    template = Task(
        title="Plantilla legacy cruzada",
        client_id=second.id,
        project_id=project.id,
        phase_id=phase.id,
        status=TaskStatus.pending,
        created_by=admin_user.id,
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=date.today().day,
    )
    db_session.add(template)
    await db_session.commit()

    @asynccontextmanager
    async def local_session():
        yield db_session

    monkeypatch.setattr("backend.db.database.async_session", local_session)
    await _generate_recurring_instances()

    count = (await db_session.execute(
        select(func.count(Task.id)).where(Task.recurring_parent_id == template.id)
    )).scalar_one()
    assert count == 0
