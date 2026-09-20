"""Global search returns only module-authorized, bounded scalar results."""
from __future__ import annotations

from sqlalchemy import event

from backend.db.models import (
    Client,
    ClientStatus,
    Lead,
    LeadStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)


async def _search_fixture(db_session, admin_id):
    client = Client(name="Needle Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Needle Project", client_id=client.id, status=ProjectStatus.active,
    )
    linked = Task(
        title="Needle linked task", status=TaskStatus.pending, client_id=client.id,
        created_by=admin_id, is_recurring=False,
    )
    orphan = Task(
        title="Needle orphan task", status=TaskStatus.pending, client_id=None,
        created_by=admin_id, is_recurring=False,
    )
    db_session.add_all([project, linked, orphan])
    await db_session.flush()
    return client, project, linked, orphan


async def test_search_tasks_keeps_clientless_rows_masks_client_and_is_bounded(
    engine, db_session, admin_user, make_member_client,
):
    client, _project, linked, orphan = await _search_fixture(db_session, admin_user.id)
    api = await make_member_client([("tasks", True, False)])
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await api.get("/api/search", params={"q": "Needle"})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
        await api.aclose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clients"] == body["projects"] == body["leads"] == []
    assert {row["id"] for row in body["tasks"]} == {linked.id, orphan.id}
    assert all(row["client_name"] is None for row in body["tasks"])
    assert client.name not in response.text
    assert sum("FROM tasks" in statement for statement in statements) == 1
    assert not any(
        f"FROM {table}" in statement
        for statement in statements
        for table in ("task_categories", "task_checklists", "projects", "clients")
    )


async def test_search_related_names_require_clients_read_permission(
    db_session, admin_user, make_member_client,
):
    client, project, linked, orphan = await _search_fixture(db_session, admin_user.id)
    projects_only = await make_member_client([("projects", True, False)])
    tasks_and_clients = await make_member_client([
        ("tasks", True, False), ("clients", True, False),
    ])
    no_modules = await make_member_client([])
    try:
        project_response = await projects_only.get("/api/search", params={"q": "Needle"})
        assert project_response.status_code == 200
        assert project_response.json()["projects"] == [{
            "id": project.id, "name": project.name,
            "client_name": None, "status": project.status.value,
        }]
        assert client.name not in project_response.text

        task_response = await tasks_and_clients.get("/api/search", params={"q": "Needle"})
        assert task_response.status_code == 200
        body = task_response.json()
        assert [row["id"] for row in body["clients"]] == [client.id]
        tasks = {row["id"]: row for row in body["tasks"]}
        assert tasks[linked.id]["client_name"] == client.name
        assert tasks[orphan.id]["client_name"] is None

        empty = await no_modules.get("/api/search", params={"q": "Needle"})
        assert empty.status_code == 200
        assert empty.json() == {"clients": [], "projects": [], "tasks": [], "leads": []}
    finally:
        await projects_only.aclose()
        await tasks_and_clients.aclose()
        await no_modules.aclose()


async def test_search_admin_sees_all_and_like_wildcards_are_literal(
    admin_client, db_session, admin_user,
):
    client, project, linked, orphan = await _search_fixture(db_session, admin_user.id)
    literal = Task(
        title="Literal 100%_done", status=TaskStatus.pending,
        created_by=admin_user.id, is_recurring=False,
    )
    wildcard_decoy = Task(
        title="Literal 100XXdone", status=TaskStatus.pending,
        created_by=admin_user.id, is_recurring=False,
    )
    db_session.add_all([literal, wildcard_decoy])
    await db_session.flush()

    visible = await admin_client.get("/api/search", params={"q": "Needle"})
    assert visible.status_code == 200
    body = visible.json()
    assert [row["id"] for row in body["clients"]] == [client.id]
    assert [row["id"] for row in body["projects"]] == [project.id]
    assert {row["id"] for row in body["tasks"]} == {linked.id, orphan.id}

    escaped = await admin_client.get("/api/search", params={"q": "%_"})
    assert escaped.status_code == 200
    assert [row["id"] for row in escaped.json()["tasks"]] == [literal.id]


async def test_search_respects_runtime_module_availability_for_admin(
    admin_client, db_session, admin_user, monkeypatch,
):
    _client, _project, linked, orphan = await _search_fixture(db_session, admin_user.id)
    lead = Lead(company_name="Needle Lead", status=LeadStatus.new)
    db_session.add(lead)
    await db_session.flush()

    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "leads")
    hidden_lead = await admin_client.get("/api/search", params={"q": "Needle"})
    assert hidden_lead.status_code == 200
    assert hidden_lead.json()["leads"] == []
    assert {row["id"] for row in hidden_lead.json()["tasks"]} == {linked.id, orphan.id}

    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "tasks")
    hidden_tasks = await admin_client.get("/api/search", params={"q": "Needle"})
    assert hidden_tasks.status_code == 200
    assert hidden_tasks.json()["tasks"] == []
    assert [row["id"] for row in hidden_tasks.json()["leads"]] == [lead.id]

    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    enabled = await admin_client.get("/api/search", params={"q": "Needle"})
    assert enabled.status_code == 200
    assert [row["id"] for row in enabled.json()["leads"]] == [lead.id]
    assert {row["id"] for row in enabled.json()["tasks"]} == {linked.id, orphan.id}
