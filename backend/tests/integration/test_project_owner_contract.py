"""Project ownership and operational task contract against real PostgreSQL."""

import asyncio
from datetime import date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Project, ProjectStatus, Task, TaskPriority, TaskStatus, User, UserRole
from backend.services.project_owner import validate_project_owner


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


async def test_member_owner_picker_exposes_activity_without_private_user_fields(member_client, db_session):
    active = await _user(db_session, active=True)
    inactive = await _user(db_session, active=False)
    response = await member_client.get("/api/users", params={"page_size": 1000})
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert rows[active.id]["is_active"] is True
    assert rows[inactive.id]["is_active"] is False
    assert rows[active.id]["email"] is None
    assert rows[active.id]["cost_per_hour"] is None


async def test_admin_owner_picker_exposes_inactive_users_as_inactive(admin_client, db_session):
    inactive = await _user(db_session, active=False)
    response = await admin_client.get("/api/users", params={"page_size": 1000})
    assert response.status_code == 200
    row = next(row for row in response.json()["items"] if row["id"] == inactive.id)
    assert row["is_active"] is False


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


async def test_project_owner_rejects_simultaneous_deactivation(engine):
    suffix = uuid4().hex
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner = User(
            email=f"owner-race-{suffix}@example.test", full_name="Responsable carrera",
            hashed_password="test", role=UserRole.member, is_active=True,
        )
        setup.add(owner)
        await setup.commit()
        owner_id = owner.id
    try:
        async with AsyncSession(engine) as deactivation:
            await deactivation.execute(
                update(User).where(User.id == owner_id).values(is_active=False)
            )
            async with AsyncSession(engine) as assignment:
                with pytest.raises(HTTPException) as exc:
                    await asyncio.wait_for(validate_project_owner(assignment, owner_id), timeout=2)
                assert exc.value.status_code == 409
                await assignment.rollback()
            await deactivation.commit()
        async with AsyncSession(engine) as assignment:
            with pytest.raises(HTTPException) as exc:
                await validate_project_owner(assignment, owner_id)
            assert exc.value.status_code == 422
    finally:
        async with AsyncSession(engine) as cleanup:
            owner = await cleanup.get(User, owner_id)
            await cleanup.delete(owner)
            await cleanup.commit()


async def test_project_owner_unchanged_inactive_can_edit_other_fields(admin_client, db_session):
    client = Client(name=f"Legacy owner {uuid4().hex[:6]}")
    owner = await _user(db_session, active=False)
    project = Project(name="Proyecto histórico", client=client, owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()
    response = await admin_client.put(f"/api/projects/{project.id}", json={
        "description": "Nota nueva", "owner_id": owner.id,
    })
    assert response.status_code == 200, response.text
    assert response.json()["owner_id"] == owner.id
    assert response.json()["description"] == "Nota nueva"


async def test_project_list_can_filter_specific_inactive_owner(admin_client, db_session):
    client = Client(name=f"Owner filter {uuid4().hex[:6]}")
    inactive = await _user(db_session, active=False)
    other = await _user(db_session, active=True)
    db_session.add_all([
        client,
        Project(name="Asignado histórico", client=client, owner_id=inactive.id),
        Project(name="Otro", client=client, owner_id=other.id),
    ])
    await db_session.flush()
    response = await admin_client.get("/api/projects", params={
        "client_id": client.id, "owner": str(inactive.id), "lifecycle": "portfolio",
    })
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()["items"]] == ["Asignado histórico"]
    invalid = await admin_client.get("/api/projects", params={"owner": "x"})
    assert invalid.status_code == 422


async def test_deactivation_impact_counts_only_operational_work(
    admin_client, member_client, db_session,
):
    owner = await _user(db_session, active=True)
    client = Client(name=f"Impact {uuid4().hex[:6]}")
    db_session.add(client)
    await db_session.flush()
    db_session.add_all([
        Project(name="Activo", client_id=client.id, owner_id=owner.id, status=ProjectStatus.active),
        Project(name="En espera", client_id=client.id, owner_id=owner.id, status=ProjectStatus.on_hold),
        Project(name="Cerrado", client_id=client.id, owner_id=owner.id, status=ProjectStatus.completed),
        Task(title="Abierta", assigned_to=owner.id, status=TaskStatus.pending),
        Task(title="Completada", assigned_to=owner.id, status=TaskStatus.completed),
        Task(title="Retirada", assigned_to=owner.id, status=TaskStatus.pending,
             retired_at=datetime(2026, 9, 21), retired_reason="Retirada"),
    ])
    await db_session.flush()

    denied = await member_client.get(f"/api/users/{owner.id}/deactivation-impact")
    assert denied.status_code == 403
    response = await admin_client.get(f"/api/users/{owner.id}/deactivation-impact")
    assert response.status_code == 200, response.text
    assert response.json() == {"open_tasks": 1, "portfolio_projects": 2}


async def test_admin_cannot_deactivate_own_account(admin_client):
    response = await admin_client.put(
        f"/api/users/{admin_client.test_user.id}", json={"is_active": False},
    )
    assert response.status_code == 422
    assert "propia cuenta" in response.json()["detail"]


async def test_admin_deactivation_revokes_access_without_erasing_assignments(
    admin_client, member_client, db_session,
):
    owner = member_client.test_user
    client = Client(name=f"Deactivation {uuid4().hex[:6]}")
    project = Project(name="Conservar responsable", client=client, owner_id=owner.id)
    task = Task(title="Conservar asignado", project=project, assigned_to=owner.id)
    db_session.add_all([client, project, task])
    await db_session.flush()
    denied = await member_client.put(f"/api/users/{owner.id}", json={"is_active": False})
    assert denied.status_code == 403

    response = await admin_client.put(f"/api/users/{owner.id}", json={"is_active": False})
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert await db_session.scalar(select(Project.owner_id).where(Project.id == project.id)) == owner.id
    assert await db_session.scalar(select(Task.assigned_to).where(Task.id == task.id)) == owner.id
    blocked = await member_client.get("/api/users")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "User is deactivated"

    renamed = await admin_client.put(
        f"/api/users/{owner.id}", json={"full_name": "Nombre histórico"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["is_active"] is False

    restored = await admin_client.put(f"/api/users/{owner.id}", json={"is_active": True})
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True


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
        "is_recurring": False,
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
