"""Project ownership and operational task contract against real PostgreSQL."""

from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import Client, Project, Task, TaskPriority, TaskStatus, User, UserRole


pytestmark = pytest.mark.integration


async def _user(db_session, *, active: bool) -> User:
    user = User(
        email=f"owner-{uuid4().hex}@example.test",
        full_name="Responsable activo" if active else "Responsable inactivo",
        hashed_password="test",
        role=UserRole.member,
        cost_per_hour=0,
        is_active=active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_project_owner_roundtrip_and_explicit_null(admin_client, db_session):
    client = Client(name=f"Owner client {uuid4().hex[:6]}")
    owner = await _user(db_session, active=True)
    db_session.add(client)
    await db_session.flush()

    created = await admin_client.post("/api/projects", json={
        "name": "Proyecto con responsable",
        "client_id": client.id,
        "owner_id": owner.id,
    })
    assert created.status_code == 201, created.text
    assert created.json()["owner_id"] == owner.id
    assert created.json()["owner_name"] == owner.full_name
    project_id = created.json()["id"]

    listed = await admin_client.get("/api/projects", params={"client_id": client.id})
    item = next(row for row in listed.json()["items"] if row["id"] == project_id)
    assert (item["owner_id"], item["owner_name"]) == (owner.id, owner.full_name)

    cleared = await admin_client.put(f"/api/projects/{project_id}", json={"owner_id": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["owner_id"] is None
    assert cleared.json()["owner_name"] is None
    assert await db_session.scalar(
        select(Project.owner_id).where(Project.id == project_id)
    ) is None


async def test_project_owner_must_exist_and_be_active(admin_client, db_session):
    client = Client(name=f"Owner validation {uuid4().hex[:6]}")
    inactive = await _user(db_session, active=False)
    db_session.add(client)
    await db_session.flush()

    inactive_response = await admin_client.post("/api/projects", json={
        "name": "No asignable",
        "client_id": client.id,
        "owner_id": inactive.id,
    })
    assert inactive_response.status_code == 422, inactive_response.text
    assert "no está activo" in inactive_response.json()["detail"]

    missing_response = await admin_client.post("/api/projects", json={
        "name": "No existe",
        "client_id": client.id,
        "owner_id": 2_000_000_000,
    })
    assert missing_response.status_code == 422, missing_response.text
    assert "no existe" in missing_response.json()["detail"]


async def test_project_tasks_contract_preserves_operational_fields(
    admin_client, db_session,
):
    client = Client(name=f"Task contract {uuid4().hex[:6]}")
    owner = await _user(db_session, active=True)
    project = Project(name="Proyecto operativo", client=client, owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()
    task = Task(
        title="Esperar aprobación",
        project_id=project.id,
        client_id=client.id,
        assigned_to=owner.id,
        status=TaskStatus.waiting,
        priority=TaskPriority.high,
        scheduled_date=date(2026, 9, 16),
        due_date=datetime(2026, 9, 18),
        waiting_for="Respuesta del cliente",
        follow_up_date=date(2026, 9, 19),
        created_by=admin_client.test_user.id,
    )
    db_session.add(task)
    await db_session.flush()

    response = await admin_client.get(f"/api/projects/{project.id}/tasks")
    assert response.status_code == 200, response.text
    row = response.json()["unassigned_tasks"][0]
    assert row == {
        "id": task.id,
        "title": "Esperar aprobación",
        "status": "waiting",
        "priority": "high",
        "start_date": None,
        "due_date": "2026-09-18T00:00:00",
        "scheduled_date": "2026-09-16",
        "estimated_minutes": None,
        "assigned_to": owner.id,
        "assigned_user_name": owner.full_name,
        "waiting_for": "Respuesta del cliente",
        "follow_up_date": "2026-09-19",
    }


async def test_template_project_accepts_only_explicit_active_owner(
    admin_client, db_session,
):
    from backend.db.models import ProjectTemplateDB

    client = Client(name=f"Template owner {uuid4().hex[:6]}")
    owner = await _user(db_session, active=True)
    template = ProjectTemplateDB(
        key=f"owner_{uuid4().hex}",
        name="Plantilla con responsable explícito",
        phases=[],
        default_tasks=[],
        created_by=admin_client.test_user.id,
    )
    db_session.add_all([client, template])
    await db_session.flush()

    response = await admin_client.post("/api/projects/from-template", params={
        "client_id": client.id,
        "template_key": template.key,
        "owner_id": owner.id,
    })
    assert response.status_code == 201, response.text
    assert response.json()["owner_id"] == owner.id
    assert response.json()["owner_name"] == owner.full_name
