from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.api.routes.inbox import _fetch_context
from backend.db.models import Client, ClientStatus, Project, ProjectStatus, Task, TaskStatus, User


async def _loaded_user(db, user_id: int) -> User:
    return (await db.execute(
        select(User).where(User.id == user_id)
        .options(selectinload(User.permissions))
        .execution_options(populate_existing=True)
    )).scalar_one()


@pytest.mark.asyncio
async def test_classifier_context_uses_real_module_permissions(
    db_session, make_member_client
):
    client = Client(name="Context Secret Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    db_session.add(Project(
        name="Context Secret Project", client_id=client.id, status=ProjectStatus.active,
    ))
    await db_session.flush()

    no_entities = await make_member_client([])
    projects_only = await make_member_client([("projects", True, False)])
    clients_only = await make_member_client([("clients", True, False)])
    try:
        hidden_projects, hidden_clients = await _fetch_context(
            db_session, await _loaded_user(db_session, no_entities.test_user.id)
        )
        assert hidden_projects == []
        assert hidden_clients == []

        projects, clients = await _fetch_context(
            db_session, await _loaded_user(db_session, projects_only.test_user.id)
        )
        project = next(p for p in projects if p["name"] == "Context Secret Project")
        assert project["client_name"] is None
        assert clients == []

        projects, clients = await _fetch_context(
            db_session, await _loaded_user(db_session, clients_only.test_user.id)
        )
        assert projects == []
        assert "Context Secret Client" in {c["name"] for c in clients}
    finally:
        await no_entities.aclose()
        await projects_only.aclose()
        await clients_only.aclose()


@pytest.mark.asyncio
async def test_briefing_defaults_to_mine_and_team_requires_admin(
    admin_client, db_session, make_member_client
):
    member = await make_member_client([("pm", True, False)])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = now.replace(hour=12, minute=0, second=0, microsecond=0)
    mine = Task(
        title="Admin own briefing", status=TaskStatus.pending,
        assigned_to=admin_client.test_user.id, created_by=admin_client.test_user.id,
        due_date=due,
    )
    theirs = Task(
        title="Member own briefing", status=TaskStatus.pending,
        assigned_to=member.test_user.id, created_by=member.test_user.id, due_date=due,
    )
    db_session.add_all([mine, theirs])
    await db_session.flush()
    try:
        admin_mine = await admin_client.get("/api/pm/daily-briefing")
        assert admin_mine.status_code == 200, admin_mine.text
        assert {t["title"] for t in admin_mine.json()["priorities"]} == {"Admin own briefing"}

        team = await admin_client.get("/api/pm/daily-briefing", params={"scope": "team"})
        assert team.status_code == 200, team.text
        assert {"Admin own briefing", "Member own briefing"}.issubset(
            {t["title"] for t in team.json()["priorities"]}
        )

        member_mine = await member.get("/api/pm/daily-briefing")
        assert member_mine.status_code == 200, member_mine.text
        assert {t["title"] for t in member_mine.json()["priorities"]} == {"Member own briefing"}
        assert (await member.get(
            "/api/pm/daily-briefing", params={"scope": "team"}
        )).status_code == 403
    finally:
        await member.aclose()


@pytest.mark.asyncio
async def test_pm_financial_source_requires_finance_income_permission(
    monkeypatch, make_member_client
):
    from backend.api.routes import pm as pm_route

    calls: list[bool] = []

    async def fake_generate(
        _db, user_id=None, *, allow_financial=False, team_scope=False
    ):
        calls.append(allow_financial)
        return []

    monkeypatch.setattr(pm_route, "generate_insights", fake_generate)
    pm_only = await make_member_client([("pm", True, True)])
    pm_finance = await make_member_client([
        ("pm", True, True), ("finance_income", True, False),
    ])
    try:
        denied_source = await pm_only.post("/api/pm/generate-insights")
        assert denied_source.status_code == 200, denied_source.text
        allowed_source = await pm_finance.post("/api/pm/generate-insights")
        assert allowed_source.status_code == 200, allowed_source.text
        assert calls == [False, True]
    finally:
        await pm_only.aclose()
        await pm_finance.aclose()
