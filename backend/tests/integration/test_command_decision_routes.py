"""HTTP command receipts expose decision queries without creating undo history."""
from datetime import datetime

import pytest
from sqlalchemy import func, select

from backend.db.models import (
    ChangeLog,
    Client,
    CommandReceipt,
    Notification,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)

pytestmark = pytest.mark.integration

DUE = datetime(2026, 9, 18, 9)  # noqa: DTZ001
DETECTED = datetime(2026, 9, 19, 10)  # noqa: DTZ001


async def add_active_incident(db, user_id: int, title: str):
    task = Task(
        title=title, assigned_to=user_id, status=TaskStatus.pending,
        due_date=DUE, is_recurring=False,
    )
    db.add(task)
    await db.flush()
    incident = Notification(
        user_id=user_id,
        type="task_overdue",
        title=f"Tarea vencida: {title}",
        message="Compromiso vencido",
        link_url=f"/tasks?task={task.id}",
        entity_type="task",
        entity_id=task.id,
        entity_key=str(task.id),
        dedupe_key=f"task_overdue:task:{task.id}:{DUE.date().isoformat()}",
        incident_state="active",
        incident_severity="warning",
        incident_revision=1,
        incident_detected_at=DETECTED,
        incident_fingerprint="c" * 64,
    )
    db.add(incident)
    await db.flush()
    return incident


def command_body(key: str, text: str):
    return {"request_key": key, "text": text, "channel": "app"}


async def test_own_command_list_and_query_pagination_are_read_only(
    admin_client, admin_user, member_user, db_session
):
    first = await add_active_incident(db_session, admin_user.id, "Decisión propia 1")
    second = await add_active_incident(db_session, admin_user.id, "Decisión propia 2")
    await add_active_incident(db_session, member_user.id, "Decisión ajena sin ACL")
    await db_session.commit()
    before = {
        row.id: (row.incident_state, row.incident_revision, row.updated_at)
        for row in (await db_session.execute(select(Notification))).scalars()
    }
    journal_before = await db_session.scalar(select(func.count(ChangeLog.id))) or 0

    created = await admin_client.post(
        "/api/commands",
        json=command_body("decision-route-own-0001", "Consulta decisiones"),
    )

    assert created.status_code == 200, created.text
    receipt = created.json()
    assert receipt["status"] == "executed"
    assert receipt["intent"] == {
        "kind": "query_work", "query": "decisions", "scope": "mine",
    }
    assert receipt["change_log_id"] is None
    assert receipt["result"]["undo_available"] is False
    assert receipt["result"]["query"]["total"] == 2
    assert [item["id"] for item in receipt["result"]["query"]["items"]] == [
        second.id, first.id,
    ]

    listed = await admin_client.get("/api/commands", params={"status": "executed"})
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [receipt["id"]]

    page_one = await admin_client.get(
        f"/api/commands/{receipt['id']}/query", params={"page": 1, "page_size": 1},
    )
    page_two = await admin_client.get(
        f"/api/commands/{receipt['id']}/query", params={"page": 2, "page_size": 1},
    )
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["has_more"] is True
    assert [item["id"] for item in page_one.json()["items"]] == [second.id]
    assert [item["id"] for item in page_two.json()["items"]] == [first.id]
    assert (await db_session.scalar(select(func.count(ChangeLog.id))) or 0) == journal_before
    after = {
        row.id: (row.incident_state, row.incident_revision, row.updated_at)
        for row in (await db_session.execute(select(Notification))).scalars()
    }
    assert after == before


async def test_team_query_is_admin_only(admin_client, admin_user, make_member_client, db_session):
    member = await make_member_client([("tasks", True, False)])
    try:
        own = await add_active_incident(db_session, admin_user.id, "Admin decide")
        teammate = await add_active_incident(
            db_session, member.test_user.id, "Miembro decide",
        )
        await db_session.commit()

        admin_response = await admin_client.post(
            "/api/commands",
            json=command_body("decision-route-team-0001", "Consulta decisiones del equipo"),
        )
        assert admin_response.status_code == 200, admin_response.text
        query = admin_response.json()["result"]["query"]
        assert query["scope"] == "team"
        assert [item["id"] for item in query["items"]] == [teammate.id, own.id]

        denied = await member.post(
            "/api/commands",
            json=command_body("decision-route-team-0002", "Consulta decisiones del equipo"),
        )
        assert denied.status_code == 403, denied.text
        failed = await db_session.scalar(select(CommandReceipt).where(
            CommandReceipt.user_id == member.test_user.id,
            CommandReceipt.request_key == "decision-route-team-0002",
        ))
        assert failed.status == "failed"
        assert failed.change_log_id is None
    finally:
        await member.aclose()


async def test_query_rechecks_acl_after_receipt_creation(
    make_member_client, db_session
):
    member = await make_member_client([("tasks", True, False)])
    try:
        incident = await add_active_incident(
            db_session, member.test_user.id, "Permiso revocable",
        )
        await db_session.commit()
        before = (incident.incident_state, incident.incident_revision, incident.updated_at)
        created = await member.post(
            "/api/commands",
            json=command_body("decision-route-revoke-01", "Consulta decisiones"),
        )
        assert created.status_code == 200, created.text
        receipt = created.json()
        assert receipt["result"]["query"]["total"] == 1

        permission = next(
            permission for permission in member.test_user.permissions
            if permission.module == "tasks"
        )
        permission.can_read = False
        await db_session.commit()

        refreshed = await member.get(f"/api/commands/{receipt['id']}/query")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["total"] == 0
        assert refreshed.json()["items"] == []
        stored = await member.get(f"/api/commands/{receipt['id']}")
        assert stored.json()["result"]["query"]["total"] == 1
        await db_session.refresh(incident)
        assert (incident.incident_state, incident.incident_revision, incident.updated_at) == before
        assert await db_session.scalar(select(func.count(ChangeLog.id))) == 0
    finally:
        await member.aclose()


async def test_project_decision_query_does_not_require_unrelated_tasks_permission(
    make_member_client, db_session
):
    member = await make_member_client([("projects", True, False)])
    try:
        client = Client(name="Cliente para cierre")
        db_session.add(client)
        await db_session.flush()
        project = Project(
            name="Cierre para decidir",
            client_id=client.id,
            status=ProjectStatus.active,
            owner_id=member.test_user.id,
            target_end_date=DUE,
        )
        db_session.add(project)
        await db_session.flush()
        incident = Notification(
            user_id=member.test_user.id,
            type="project_closing_overdue",
            title="Cierre vencido: Cierre para decidir",
            message="El compromiso de cierre está vencido",
            link_url=f"/projects/{project.id}",
            entity_type="project",
            entity_id=project.id,
            entity_key=str(project.id),
            dedupe_key=(
                f"project_closing_overdue:project:{project.id}:{DUE.date().isoformat()}"
            ),
            incident_state="active",
            incident_severity="critical",
            incident_revision=1,
            incident_detected_at=DETECTED,
            incident_fingerprint="p" * 64,
        )
        db_session.add(incident)
        await db_session.commit()

        response = await member.post(
            "/api/commands",
            json=command_body("decision-project-only-01", "Consulta decisiones"),
        )

        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["query"]["total"] == 1
        assert result["query"]["items"][0]["id"] == incident.id
        assert result["undo_available"] is False
        assert response.json()["change_log_id"] is None
    finally:
        await member.aclose()
