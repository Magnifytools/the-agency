"""Receipt reads must respect permissions granted at read time."""

import pytest
from datetime import datetime, time, timedelta
from sqlalchemy import select

from backend.db.models import Client, CommandReceipt, Notification, Project, Task, TaskStatus, UserPermission, UserRole
from backend.services.temporal import business_today

pytestmark = pytest.mark.asyncio


async def test_task_query_receipt_is_redacted_after_read_revocation(make_member_client, db_session):
    client = await make_member_client([("tasks", True, False)])
    try:
        db_session.add(Task(title="Secreto P67", status=TaskStatus.pending, assigned_to=client.test_user.id))
        await db_session.commit()
        body = {"request_key": "p67-task-query-replay-key", "text": "Consulta prioridades"}
        initial = await client.post("/api/commands", json=body)
        assert initial.status_code == 200, initial.text
        receipt = initial.json()
        assert "Secreto P67" in str(receipt["result"])

        permission = await db_session.scalar(select(UserPermission).where(
            UserPermission.user_id == client.test_user.id, UserPermission.module == "tasks",
        ))
        permission.can_read = False
        await db_session.commit()

        for response in (
            await client.get(f"/api/commands/{receipt['id']}"),
            await client.get("/api/commands"),
            await client.post("/api/commands", json=body),
        ):
            assert response.status_code == 200, response.text
            data = response.json()
            assert "Secreto P67" not in str(data)
        stored = await db_session.get(CommandReceipt, receipt["id"])
        assert "Secreto P67" in str(stored.result)
        fresh = await client.get(f"/api/commands/{receipt['id']}/query")
        assert fresh.status_code == 403
    finally:
        await client.aclose()


async def test_team_decisions_receipt_is_redacted_after_admin_demoted(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, False)])
    try:
        due = business_today() - timedelta(days=1)
        task = Task(title="Decisión P67", status=TaskStatus.pending,
                    due_date=datetime.combine(due, time.min), assigned_to=member.test_user.id)
        db_session.add(task)
        await db_session.flush()
        db_session.add(Notification(
            user_id=member.test_user.id, type="task_overdue", title="Decisión P67",
            message="Mensaje privado P67", entity_type="task", entity_id=task.id,
            entity_key=str(task.id), incident_state="active", incident_revision=1,
            dedupe_key=f"task_overdue:task:{task.id}:{due.isoformat()}",
            incident_severity="warning", incident_detected_at=datetime.combine(due, time.min),
            link_url=f"/tasks?task={task.id}",
        ))
        await db_session.commit()
        body = {"request_key": "p67-team-decision-replay", "text": "Consulta decisiones del equipo"}
        initial = await admin_client.post("/api/commands", json=body)
        assert initial.status_code == 200, initial.text
        receipt = initial.json()
        assert "Mensaje privado P67" in str(receipt["result"])

        admin_client.test_user.role = UserRole.member
        await db_session.merge(admin_client.test_user)
        await db_session.commit()
        for response in (
            await admin_client.get(f"/api/commands/{receipt['id']}"),
            await admin_client.get("/api/commands"),
            await admin_client.post("/api/commands", json=body),
        ):
            assert response.status_code == 200, response.text
            assert "Mensaje privado P67" not in str(response.json())
        stored = await db_session.get(CommandReceipt, receipt["id"])
        assert "Mensaje privado P67" in str(stored.result)
        fresh = await admin_client.get(f"/api/commands/{receipt['id']}/query")
        assert fresh.status_code == 403
    finally:
        await member.aclose()


async def test_task_choice_does_not_keep_project_subtitle_after_partial_revocation(
    make_member_client, db_session,
):
    client = await make_member_client([("tasks", True, True), ("projects", True, False)])
    try:
        owner = Client(name="Cliente P67")
        db_session.add(owner)
        await db_session.flush()
        project = Project(name="Proyecto reservado P67", client_id=owner.id)
        db_session.add(project)
        await db_session.flush()
        db_session.add_all([
            Task(title="Duplicada P67", status=TaskStatus.pending, project_id=project.id),
            Task(title="Duplicada P67", status=TaskStatus.pending),
        ])
        await db_session.commit()
        body = {"request_key": "p67-partial-prompt-replay", "text": "Completa la tarea Duplicada P67"}
        initial = await client.post("/api/commands", json=body)
        assert initial.status_code == 200, initial.text
        receipt = initial.json()
        assert receipt["status"] == "needs_input"
        assert "Proyecto reservado P67" in str(receipt["prompt"])

        permission = await db_session.scalar(select(UserPermission).where(
            UserPermission.user_id == client.test_user.id, UserPermission.module == "projects",
        ))
        permission.can_read = False
        await db_session.commit()
        for response in (
            await client.get(f"/api/commands/{receipt['id']}"),
            await client.get("/api/commands"),
            await client.post("/api/commands", json=body),
        ):
            assert response.status_code == 200, response.text
            assert "Proyecto reservado P67" not in str(response.json())
        stored = await db_session.get(CommandReceipt, receipt["id"])
        assert "Proyecto reservado P67" in str(stored.prompt)
    finally:
        await client.aclose()


async def test_authorized_query_receipt_uses_current_task_rows(make_member_client, db_session):
    client = await make_member_client([("tasks", True, False)])
    try:
        task = Task(title="Antes P67", status=TaskStatus.pending, assigned_to=client.test_user.id)
        db_session.add(task)
        await db_session.commit()
        receipt = (await client.post("/api/commands", json={
            "request_key": "p67-fresh-query-replay", "text": "Consulta prioridades",
        })).json()
        assert "Antes P67" in str(receipt["result"])
        task.assigned_to = None
        await db_session.commit()
        current = await client.get(f"/api/commands/{receipt['id']}")
        assert current.status_code == 200
        assert current.json()["result"]["query"]["items"] == []
        assert "Antes P67" not in str(current.json())
        stored = await db_session.get(CommandReceipt, receipt["id"])
        assert "Antes P67" in str(stored.result)
    finally:
        await client.aclose()


async def test_client_label_in_task_receipt_is_hidden_after_clients_revoked(
    make_member_client, db_session,
):
    client = await make_member_client([("tasks", True, True), ("clients", True, False)])
    try:
        owner = Client(name="Cliente privado P67")
        db_session.add(owner)
        await db_session.commit()
        body = {"request_key": "p67-client-label-replay",
                "text": 'Crea tarea "Entrega P67" para cliente "Cliente privado P67"'}
        initial = await client.post("/api/commands", json=body)
        assert initial.status_code == 200, initial.text
        receipt = initial.json()
        assert "Cliente privado P67" in str(receipt["result"])
        permission = await db_session.scalar(select(UserPermission).where(
            UserPermission.user_id == client.test_user.id, UserPermission.module == "clients",
        ))
        permission.can_read = False
        await db_session.commit()
        current = await client.get(f"/api/commands/{receipt['id']}")
        assert current.status_code == 200
        assert "Cliente privado P67" not in str(current.json()["result"])
        assert current.json()["result"]["undo_available"] is False
        stored = await db_session.get(CommandReceipt, receipt["id"])
        assert "Cliente privado P67" in str(stored.result)
    finally:
        await client.aclose()
