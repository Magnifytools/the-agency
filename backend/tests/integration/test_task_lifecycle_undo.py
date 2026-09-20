"""Real HTTP/journal checks for review and wait inverses, including legacy dates."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db.models import ChangeLog, Client, Project, Task, TaskStatus
from backend.services.temporal import business_today

pytestmark = pytest.mark.asyncio


async def seed(db, *, owner, task_status=TaskStatus.pending, **task_fields):
    client = Client(name="Lifecycle undo client")
    db.add(client)
    await db.flush()
    project = Project(name="Lifecycle project", client_id=client.id, owner_id=owner)
    db.add(project)
    await db.flush()
    task = Task(title="Lifecycle work", client_id=client.id, project_id=project.id,
                status=task_status, **task_fields)
    db.add(task)
    await db.commit()
    return project, task


async def last_change(db, actor):
    return await db.scalar(select(ChangeLog).where(ChangeLog.user_id == actor).order_by(ChangeLog.id.desc()).limit(1))


async def test_undo_cannot_restore_completion_after_project_requires_review(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, True)])
    try:
        project, task = await seed(db_session, owner=admin_client.test_user.id, task_status=TaskStatus.completed)
        task_id, project_id, actor_id = task.id, project.id, member.test_user.id
        response = await member.put(f"/api/tasks/{task_id}", json={"status": "pending"})
        assert response.status_code == 200, response.text
        entry = await last_change(db_session, actor_id)
        entry_id = entry.id
        response = await admin_client.put(f"/api/projects/{project_id}", json={"requires_task_review": True})
        assert response.status_code == 200, response.text
        response = await member.post(f"/api/changes/{entry_id}/undo")
        assert response.status_code == 409, response.text
        assert "revisión" in response.json()["detail"]
        await db_session.refresh(task)
        await db_session.refresh(entry)
        assert task.status == TaskStatus.pending
        assert entry.undone_at is None
    finally:
        await member.aclose()


async def test_undo_annotation_of_old_completion_preserves_unknown_date_under_policy(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, True)])
    try:
        project, task = await seed(db_session, owner=admin_client.test_user.id, task_status=TaskStatus.completed)
        task_id, project_id, actor_id = task.id, project.id, member.test_user.id
        response = await admin_client.put(f"/api/projects/{project_id}", json={"requires_task_review": True})
        assert response.status_code == 200, response.text
        response = await member.put(f"/api/tasks/{task_id}", json={"title": "Annotation only"})
        assert response.status_code == 200, response.text
        entry = await last_change(db_session, actor_id)
        response = await member.post(f"/api/changes/{entry.id}/undo")
        assert response.status_code == 200, response.text
        await db_session.refresh(task)
        assert task.title == "Lifecycle work"
        assert task.status == TaskStatus.completed
        assert task.completed_at is None
    finally:
        await member.aclose()


async def test_undo_waiting_restores_original_expired_date_without_inventing_followup(
    admin_client, db_session,
):
    yesterday = business_today() - timedelta(days=1)
    _, task = await seed(db_session, owner=admin_client.test_user.id,
        task_status=TaskStatus.waiting, waiting_for="Respuesta de cliente",
        assigned_to=admin_client.test_user.id, follow_up_date=yesterday)
    task_id = task.id
    response = await admin_client.put(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    assert response.status_code == 200, response.text
    entry = await last_change(db_session, admin_client.test_user.id)
    response = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert response.status_code == 200, response.text
    await db_session.refresh(task)
    assert task.status == TaskStatus.waiting
    assert task.follow_up_date == yesterday
    assert task.waiting_for == "Respuesta de cliente"


async def test_bulk_completion_returns_per_task_review_failure_and_real_success(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, True)])
    try:
        project, protected = await seed(db_session, owner=admin_client.test_user.id)
        plain = Task(title="Direct work", status=TaskStatus.pending)
        db_session.add(plain)
        await db_session.commit()
        protected_id, plain_id = protected.id, plain.id
        response = await admin_client.put(f"/api/projects/{project.id}", json={"requires_task_review": True})
        assert response.status_code == 200, response.text
        response = await member.patch("/api/tasks/bulk/update", json={
            "ids": [protected_id, plain_id], "updates": {"status": "completed"},
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["updated"], body["failed"], body["requested"]) == (1, 1, 2)
        results = {item["id"]: item for item in body["results"]}
        assert results[plain_id]["updated"] is True
        assert results[protected_id]["updated"] is False
        assert "revisión" in results[protected_id]["detail"]
        await db_session.refresh(protected)
        await db_session.refresh(plain)
        assert protected.status == TaskStatus.pending
        assert plain.status == TaskStatus.completed
    finally:
        await member.aclose()
