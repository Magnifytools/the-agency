"""Optional project review policy against real PostgreSQL state."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db.models import (
    Client,
    CommandReceipt,
    Project,
    ProjectPhase,
    Task,
    TaskStatus,
    User,
    UserPermission,
    UserRole,
)
from backend.services.domain_writes import create_task, update_task
from backend.services.task_review import validate_task_review

pytestmark = pytest.mark.integration


async def _user(db_session, *, role=UserRole.member, active=True, tasks_write=True):
    user = User(
        email=f"review-{uuid4().hex}@example.test",
        full_name="Reviewer",
        hashed_password="test",
        role=role,
        cost_per_hour=0,
        is_active=active,
    )
    db_session.add(user)
    await db_session.flush()
    if tasks_write:
        db_session.add(UserPermission(
            user_id=user.id, module="tasks", can_read=True, can_write=True,
        ))
        await db_session.flush()
    return user


async def _project(db_session, *, owner, review=True):
    client = Client(name=f"Review client {uuid4().hex[:8]}")
    project = Project(
        name="Review project",
        client=client,
        owner_id=owner.id if owner else None,
        requires_task_review=review,
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def test_project_policy_roundtrip_and_requires_active_owner(admin_client, db_session):
    owner = await _user(db_session)
    inactive = await _user(db_session, active=False)
    client = Client(name=f"Policy route {uuid4().hex[:8]}")
    db_session.add(client)
    await db_session.flush()

    missing_owner = await admin_client.post("/api/projects", json={
        "name": "No owner", "client_id": client.id, "requires_task_review": True,
    })
    assert missing_owner.status_code == 422
    assert "responsable activo" in missing_owner.json()["detail"]

    inactive_owner = await admin_client.post("/api/projects", json={
        "name": "Inactive owner", "client_id": client.id, "owner_id": inactive.id,
        "requires_task_review": True,
    })
    assert inactive_owner.status_code == 422
    assert "no está activo" in inactive_owner.json()["detail"]

    created = await admin_client.post("/api/projects", json={
        "name": "Reviewed", "client_id": client.id, "owner_id": owner.id,
        "requires_task_review": True,
    })
    assert created.status_code == 201, created.text
    assert created.json()["requires_task_review"] is True
    project_id = created.json()["id"]

    listed = await admin_client.get("/api/projects", params={"client_id": client.id})
    item = next(row for row in listed.json()["items"] if row["id"] == project_id)
    assert item["requires_task_review"] is True

    disabled = await admin_client.put(
        f"/api/projects/{project_id}", json={"requires_task_review": False, "owner_id": None},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["requires_task_review"] is False
    assert disabled.json()["owner_id"] is None

    legacy = Project(name="Legacy ownerless", client_id=client.id)
    db_session.add(legacy)
    await db_session.flush()
    renamed = await admin_client.put(f"/api/projects/{legacy.id}", json={"name": "Still legacy"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["requires_task_review"] is False
    cannot_activate = await admin_client.put(
        f"/api/projects/{legacy.id}", json={"requires_task_review": True},
    )
    assert cannot_activate.status_code == 422
    null_policy = await admin_client.put(
        f"/api/projects/{legacy.id}", json={"requires_task_review": None},
    )
    assert null_policy.status_code == 422
    assert "Indica si" in null_policy.json()["detail"]


async def test_concrete_completion_requires_fresh_owner_or_admin(db_session):
    owner = await _user(db_session)
    other = await _user(db_session)
    admin = await _user(db_session, role=UserRole.admin)
    project = await _project(db_session, owner=owner)

    with pytest.raises(HTTPException) as denied:
        await validate_task_review(
            db_session, {"project_id": project.id, "status": TaskStatus.completed}, other,
        )
    assert denied.value.status_code == 409
    assert "status=in_review" in denied.value.detail

    with pytest.raises(HTTPException):
        await validate_task_review(
            db_session, {"project_id": project.id, "status": TaskStatus.completed}, None,
        )

    owner_context = await validate_task_review(
        db_session, {"project_id": project.id, "status": TaskStatus.completed}, owner,
    )
    admin_context = await validate_task_review(
        db_session, {"project_id": project.id, "status": TaskStatus.completed}, admin,
    )
    assert owner_context.requires_review is True
    assert admin_context.requires_review is True

    # The actor object may be stale: authority comes from the current DB row.
    stale_admin = SimpleNamespace(id=other.id, role=UserRole.admin)
    with pytest.raises(HTTPException):
        await validate_task_review(
            db_session, {"project_id": project.id, "status": TaskStatus.completed}, stale_admin,
        )


async def test_policy_only_checks_real_scope_transitions(db_session):
    owner = await _user(db_session)
    other = await _user(db_session)
    project = await _project(db_session, owner=owner)
    task = Task(
        title="Historical completion",
        client_id=project.client_id,
        project_id=project.id,
        status=TaskStatus.completed,
        is_recurring=False,
        created_by=owner.id,
    )
    db_session.add(task)
    await db_session.flush()

    # Editing metadata or repeating the current state must not retroactively
    # require the reviewer for an already completed historical task.
    await validate_task_review(db_session, {"title": "Edited"}, other, existing=task)
    await validate_task_review(
        db_session, {"status": TaskStatus.completed}, other, existing=task,
    )
    # Explicit review and recurring templates remain outside completion policy.
    await validate_task_review(
        db_session, {"status": TaskStatus.in_review}, other, existing=task,
    )
    await validate_task_review(db_session, {
        "project_id": project.id, "status": TaskStatus.completed, "is_recurring": True,
    }, other)

    pending = Task(
        title="Pending",
        client_id=project.client_id,
        status=TaskStatus.completed,
        is_recurring=False,
        created_by=owner.id,
    )
    db_session.add(pending)
    await db_session.flush()
    with pytest.raises(HTTPException):
        await validate_task_review(
            db_session, {"project_id": project.id}, other, existing=pending,
        )

    template = Task(
        title="Template",
        client_id=project.client_id,
        project_id=project.id,
        status=TaskStatus.completed,
        is_recurring=True,
        created_by=owner.id,
    )
    db_session.add(template)
    await db_session.flush()
    with pytest.raises(HTTPException):
        await validate_task_review(
            db_session, {"is_recurring": False}, other, existing=template,
        )


async def test_domain_writer_cannot_disguise_concrete_completion_as_template(db_session):
    owner = await _user(db_session)
    other = await _user(db_session)
    project = await _project(db_session, owner=owner)
    task = await create_task(db_session, {
        "title": "Concrete task", "client_id": project.client_id,
        "project_id": project.id, "status": TaskStatus.pending,
    }, actor=other)

    with pytest.raises(HTTPException) as denied:
        await update_task(db_session, task, {
            "status": TaskStatus.completed,
            "is_recurring": True,
            "recurrence_pattern": "weekly",
            "recurrence_day": 1,
        }, actor=other)
    assert denied.value.status_code == 409
    await db_session.refresh(task)
    assert task.status == TaskStatus.pending
    assert task.is_recurring is False

    template = await create_task(db_session, {
        "title": "Real template", "client_id": project.client_id,
        "project_id": project.id, "status": TaskStatus.completed,
        "is_recurring": True, "recurrence_pattern": "weekly", "recurrence_day": 1,
    }, actor=other)
    assert template.status == TaskStatus.completed
    assert template.is_recurring is True


async def test_phase_only_scope_is_reviewed_after_project_inference(db_session):
    owner = await _user(db_session)
    other = await _user(db_session)
    project = await _project(db_session, owner=owner)
    phase = ProjectPhase(name="Review phase", project_id=project.id)
    unscoped = Task(title="Infer on update", status=TaskStatus.pending, created_by=other.id)
    db_session.add_all([phase, unscoped])
    await db_session.flush()

    with pytest.raises(HTTPException) as denied_update:
        await update_task(db_session, unscoped, {
            "phase_id": phase.id, "status": TaskStatus.completed,
        }, actor=other)
    assert denied_update.value.status_code == 409
    await db_session.refresh(unscoped)
    assert unscoped.project_id is None
    assert unscoped.status == TaskStatus.pending

    accepted_update = await update_task(db_session, unscoped, {
        "phase_id": phase.id, "status": TaskStatus.completed,
    }, actor=owner)
    assert accepted_update.project_id == project.id
    assert accepted_update.phase_id == phase.id
    assert accepted_update.status == TaskStatus.completed

    with pytest.raises(HTTPException) as denied_create:
        await create_task(db_session, {
            "title": "Infer on create", "phase_id": phase.id,
            "status": TaskStatus.completed,
        }, actor=other)
    assert denied_create.value.status_code == 409

    accepted_create = await create_task(db_session, {
        "title": "Owner phase create", "phase_id": phase.id,
        "status": TaskStatus.completed,
    }, actor=owner)
    assert accepted_create.project_id == project.id
    assert accepted_create.client_id == project.client_id
    assert accepted_create.status == TaskStatus.completed


async def test_bulk_and_command_report_review_failure_without_false_success(
    db_session, make_member_client,
):
    owner = await _user(db_session)
    project = await _project(db_session, owner=owner)
    bulk_task = Task(
        title="Bulk needs review", client_id=project.client_id, project_id=project.id,
        status=TaskStatus.pending,
    )
    command_task = Task(
        title="Command needs review", client_id=project.client_id, project_id=project.id,
        status=TaskStatus.pending,
    )
    db_session.add_all([bulk_task, command_task])
    await db_session.flush()
    bulk_task_id = bulk_task.id
    command_task_id = command_task.id

    client = await make_member_client([("tasks", True, True)])
    async with client:
        bulk = await client.patch("/api/tasks/bulk/update", json={
            "ids": [bulk_task_id], "updates": {"status": "completed"},
        })
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["updated"] == 0
        assert bulk.json()["failed"] == 1
        assert "status=in_review" in bulk.json()["results"][0]["detail"]

        command = await client.post("/api/commands", json={
            "request_key": "review-command-000001",
            "text": "Completa la tarea Command needs review",
            "channel": "app",
        })
        assert command.status_code == 409, command.text

        receipt = await db_session.scalar(select(CommandReceipt).where(
            CommandReceipt.user_id == client.test_user.id,
            CommandReceipt.request_key == "review-command-000001",
        ))
        assert receipt.status == "failed"
        assert receipt.error_code == "invalid_command"
        assert "status=in_review" in receipt.error_detail
        assert not (receipt.result or {}).get("entities")

    db_session.expire_all()
    assert (await db_session.get(Task, bulk_task_id)).status == TaskStatus.pending
    assert (await db_session.get(Task, command_task_id)).status == TaskStatus.pending


async def test_tasks_only_member_gets_minimal_review_context_without_project_access(
    db_session, make_member_client,
):
    owner = await _user(db_session)
    project = await _project(db_session, owner=owner)
    client = await make_member_client([("tasks", True, True)])
    member_id = client.test_user.id
    task = Task(
        title="Visible review context",
        client_id=project.client_id,
        project_id=project.id,
        assigned_to=member_id,
        scheduled_date=date(2026, 9, 22),
        status=TaskStatus.pending,
        created_by=owner.id,
    )
    db_session.add(task)
    await db_session.flush()
    task_id = task.id

    async with client:
        forbidden_projects = await client.get("/api/projects")
        assert forbidden_projects.status_code == 403

        detail = await client.get(f"/api/tasks/{task_id}")
        assert detail.status_code == 200, detail.text
        listed = await client.get("/api/tasks", params={"page_size": 100})
        assert listed.status_code == 200, listed.text
        agenda = await client.get("/api/tasks/agenda", params={
            "date": "2026-09-22", "section": "planned", "assigned_to": "me",
        })
        assert agenda.status_code == 200, agenda.text

    rows = [
        detail.json(),
        next(row for row in listed.json()["items"] if row["id"] == task_id),
        next(row for row in agenda.json()["items"] if row["id"] == task_id),
    ]
    for row in rows:
        assert row["project_requires_task_review"] is True
        assert row["project_review_owner_id"] == owner.id
        assert "monthly_fee" not in row
        assert "budget_amount" not in row
