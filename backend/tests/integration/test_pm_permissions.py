from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.services.inbox_processing import fetch_context as _fetch_context
from backend.db.models import (
    Client,
    ClientStatus,
    InsightPriority,
    InsightStatus,
    InsightType,
    PMInsight,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    User,
)


async def _loaded_user(db, user_id: int) -> User:
    return (
        await db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.permissions))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_classifier_context_uses_real_module_permissions(
    db_session, make_member_client
):
    client = Client(name="Context Secret Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    db_session.add(
        Project(
            name="Context Secret Project",
            client_id=client.id,
            status=ProjectStatus.active,
        )
    )
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
    from backend.services.temporal import business_today

    # At 22:00 UTC the Agency is already on the next civil day. Keep deadline
    # and planning on that same business date instead of deriving one from UTC.
    assert business_today(now=datetime(2026, 9, 20, 22, tzinfo=timezone.utc)) == date(2026, 9, 21)
    planned = business_today()
    due = datetime.combine(planned, time(hour=12))
    mine = Task(
        title="Admin own briefing",
        status=TaskStatus.pending,
        assigned_to=admin_client.test_user.id,
        created_by=admin_client.test_user.id,
        due_date=due,
        scheduled_date=planned,
    )
    theirs = Task(
        title="Member own briefing",
        status=TaskStatus.pending,
        assigned_to=member.test_user.id,
        created_by=member.test_user.id,
        due_date=due,
        scheduled_date=planned,
    )
    db_session.add_all([mine, theirs])
    await db_session.flush()
    try:
        admin_mine = await admin_client.get("/api/pm/daily-briefing")
        assert admin_mine.status_code == 200, admin_mine.text
        assert {t["title"] for t in admin_mine.json()["priorities"]} == {
            "Admin own briefing"
        }

        team = await admin_client.get(
            "/api/pm/daily-briefing", params={"scope": "team"}
        )
        assert team.status_code == 200, team.text
        assert {"Admin own briefing", "Member own briefing"}.issubset(
            {t["title"] for t in team.json()["priorities"]}
        )

        member_mine = await member.get("/api/pm/daily-briefing")
        assert member_mine.status_code == 200, member_mine.text
        assert {t["title"] for t in member_mine.json()["priorities"]} == {
            "Member own briefing"
        }
        assert (
            await member.get("/api/pm/daily-briefing", params={"scope": "team"})
        ).status_code == 403
    finally:
        await member.aclose()


@pytest.mark.asyncio
async def test_retired_pm_generator_requires_pm_write_and_returns_gone(
    make_member_client,
):
    pm_only = await make_member_client([("pm", True, True)])
    pm_read_only = await make_member_client([("pm", True, False)])
    try:
        retired = await pm_only.post("/api/pm/generate-insights")
        assert retired.status_code == 410, retired.text
        assert "/incidents" in retired.json()["detail"]
        assert (await pm_read_only.post("/api/pm/generate-insights")).status_code == 403
    finally:
        await pm_only.aclose()
        await pm_read_only.aclose()


@pytest.mark.asyncio
async def test_hidden_finance_disables_source_even_for_admin(
    monkeypatch, admin_client, db_session
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "finance")
    db_session.add(
        PMInsight(
            insight_type=InsightType.financial,
            priority=InsightPriority.high,
            title="Importe oculto por capacidad",
            description="No debe salir",
            status=InsightStatus.active,
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            user_id=admin_client.test_user.id,
        )
    )
    await db_session.flush()
    listed = await admin_client.get("/api/pm/insights")
    counted = await admin_client.get("/api/pm/insights/count")
    assert "Importe oculto por capacidad" not in {
        item["title"] for item in listed.json()
    }
    assert counted.json()["total"] == 0
    response = await admin_client.post("/api/pm/generate-insights")
    assert response.status_code == 410, response.text


@pytest.mark.asyncio
async def test_lost_finance_permission_hides_persisted_financial_insight(
    db_session, make_member_client
):
    member = await make_member_client(
        [
            ("pm", True, True),
            ("finance_income", True, False),
        ]
    )
    insight = PMInsight(
        insight_type=InsightType.financial,
        priority=InsightPriority.high,
        title="Importe privado 900€",
        description="Cobro pendiente",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=member.test_user.id,
    )
    db_session.add(insight)
    legacy_overdue = PMInsight(
        insight_type=InsightType.overdue,
        priority=InsightPriority.high,
        title="Legacy ambiguo 700€",
        description="Sin provenance histórica",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=member.test_user.id,
        task_id=None,
    )
    legacy_suggestion = PMInsight(
        insight_type=InsightType.suggestion,
        priority=InsightPriority.low,
        title="Sugerencia legacy mezclada",
        description="Pudo derivar de importes",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=member.test_user.id,
    )
    safe_suggestion = PMInsight(
        insight_type=InsightType.operational_suggestion,
        priority=InsightPriority.low,
        title="Sugerencia operativa segura",
        description="Solo tareas",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=member.test_user.id,
    )
    db_session.add_all([legacy_overdue, legacy_suggestion, safe_suggestion])
    await db_session.flush()
    try:
        visible = await member.get("/api/pm/insights")
        assert visible.status_code == 200
        assert "Importe privado 900€" in {item["title"] for item in visible.json()}

        actor = await _loaded_user(db_session, member.test_user.id)
        finance_permission = next(
            p for p in actor.permissions if p.module == "finance_income"
        )
        await db_session.delete(finance_permission)
        await db_session.flush()
        db_session.expire(actor, ["permissions"])

        hidden = await member.get("/api/pm/insights")
        count = await member.get("/api/pm/insights/count")
        assert hidden.status_code == count.status_code == 200
        assert "Importe privado 900€" not in {item["title"] for item in hidden.json()}
        remaining = {item["title"] for item in hidden.json()}
        assert remaining == {"Sugerencia operativa segura"}
        assert count.json()["total"] == 1
        assert (
            await member.put(f"/api/pm/insights/{insight.id}/dismiss")
        ).status_code == 403
        assert (
            await member.put(f"/api/pm/insights/{legacy_overdue.id}/act")
        ).status_code == 403
    finally:
        await member.aclose()


@pytest.mark.asyncio
async def test_failed_regeneration_preserves_previous_insights(
    db_session, make_member_client
):
    member = await make_member_client([("pm", True, True)])
    old = PMInsight(
        insight_type=InsightType.quality,
        priority=InsightPriority.low,
        title="Hallazgo anterior",
        description="Debe sobrevivir",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=member.test_user.id,
    )
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    try:
        response = await member.post("/api/pm/generate-insights")
        assert response.status_code == 410
        assert await db_session.get(PMInsight, old_id) is not None
        titles = set(
            (
                await db_session.execute(
                    select(PMInsight.title).where(
                        PMInsight.user_id == member.test_user.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert titles == {"Hallazgo anterior"}
    finally:
        await member.aclose()


@pytest.mark.asyncio
async def test_startup_migration_knows_pm_insight_enum_values(engine, monkeypatch):
    from sqlalchemy import text

    from backend.db import database as db_module
    from backend.startup import migrations

    monkeypatch.setattr(db_module, "engine", engine)
    await migrations._ensure_enum_values()
    async with engine.begin() as connection:
        labels = set(
            (
                await connection.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
                        "WHERE t.typname='insighttype'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {"financial", "operational_suggestion"}.issubset(labels)


@pytest.mark.asyncio
async def test_financial_rows_never_enter_operational_ai_prompt(
    db_session, monkeypatch
):
    from backend.services import insights as insights_service

    financial = PMInsight(
        insight_type=InsightType.financial,
        priority=InsightPriority.high,
        title="1.200€ pendientes",
        description="Dato financiero sensible",
        status=InsightStatus.active,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    seen: list[list[PMInsight]] = []

    async def fake_financial(*_args, **_kwargs):
        return [financial]

    async def fake_ai(rows, _user_id):
        seen.append(list(rows))

    monkeypatch.setattr(
        insights_service, "_generate_overdue_income_insights", fake_financial
    )
    monkeypatch.setattr(insights_service, "_enhance_insights_with_ai", fake_ai)
    generated = await insights_service.generate_insights(
        db_session, allow_financial=True, commit=False
    )
    assert financial in generated
    assert len(seen) == 1
    assert financial not in seen[0]
    assert all(row.insight_type != InsightType.financial for row in seen[0])


@pytest.mark.asyncio
async def test_member_cannot_share_team_briefing(make_member_client):
    member = await make_member_client([("pm", True, True)])
    try:
        response = await member.post(
            "/api/pm/briefing/discord", params={"scope": "team"}
        )
        assert response.status_code == 403
    finally:
        await member.aclose()


@pytest.mark.asyncio
async def test_share_uses_requested_authorized_scope(admin_client, monkeypatch):
    import httpx

    from backend.api.routes import pm as route
    from backend.config import settings

    scopes = []

    async def briefing(_db, user_id, team=False, include_ai=False):
        scopes.append((user_id, team))
        return {
            "greeting": "Prueba",
            "date": "2026-09-17",
            "priorities": [],
            "alerts": [],
            "followups": [],
        }

    original_client = httpx.AsyncClient
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(route, "get_daily_briefing", briefing)
    monkeypatch.setattr(
        settings,
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123/fake-test-token",
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(send), **kwargs),
    )
    response = await admin_client.post(
        "/api/pm/briefing/discord", params={"scope": "team"}
    )
    assert response.status_code == 202, response.text
    assert response.json()["success"] is False
    assert scopes == [(admin_client.test_user.id, True)]
    assert len(requests) == 0  # Request durably queued, no provider HTTP.
