"""SEO traffic drop incidents read the synced Engine summary on real Postgres."""
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, Notification, Project, ProjectStatus, User, UserPermission, UserRole,
)
from backend.services.incident_client_conditions import (
    CLIENT_SEO_TRAFFIC_DROP, client_visibility_clause, collect_client_conditions,
)
from backend.services.incidents import reconcile_recipient, visible_incident_clause

NOW = datetime(2026, 10, 18, 9)  # noqa: DTZ001 - application stores naive UTC


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 100)


def _summary(clicks, previous):
    return {
        "as_of": "2026-10-17", "clicks_30d": clicks, "clicks_previous_30d": previous,
        "impressions_30d": 9000, "impressions_previous_30d": 10000,
    }


async def _user(db, role=UserRole.member, modules=("clients",)):
    user = User(
        email=f"seo-incidents-{uuid4().hex}@test.local", full_name="SEO owner",
        hashed_password="test", role=role, is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add_all([UserPermission(user_id=user.id, module=m, can_read=True, can_write=False) for m in modules])
    await db.flush()
    return user


async def _client(db, summary, **fields):
    client = Client(
        name=fields.pop("name", f"SEO client {uuid4().hex[:8]}"), engine_project_id=fields.pop("engine_project_id", 7),
        engine_summary_data=summary, **fields,
    )
    db.add(client)
    await db.flush()
    return client


async def _own(db, client, owner, status=ProjectStatus.active):
    db.add(Project(name="SEO", client_id=client.id, owner_id=owner.id, status=status))
    await db.flush()


async def _visible(db, user_id, current_only=True):
    return (await db.execute(select(Notification).where(
        Notification.type == CLIENT_SEO_TRAFFIC_DROP,
        visible_incident_clause(user_id, current_only=current_only),
    ))).scalars().all()


async def test_only_real_drops_on_active_linked_clients_raise_a_condition(db_session):
    owner = await _user(db_session)
    dropping = await _client(db_session, _summary(400, 1000))
    for client in [
        dropping,
        await _client(db_session, _summary(850, 1000)),                       # -15 %: below threshold
        await _client(db_session, _summary(10, 90)),                          # too little volume
        await _client(db_session, _summary(400, 1000), status=ClientStatus.paused),
        await _client(db_session, _summary(400, 1000), is_internal=True),
        await _client(db_session, _summary(400, 1000), engine_project_id=None),
        await _client(db_session, {"clicks_30d": "400", "clicks_previous_30d": 1000}),  # malformed
        await _client(db_session, {"clicks_30d": "abc", "clicks_previous_30d": "1.000"}),
        await _client(db_session, {"clicks_30d": {"v": 1}, "clicks_previous_30d": [1000]}),
        await _client(db_session, None),
    ]:
        await _own(db_session, client, owner)

    conditions = await collect_client_conditions(db_session, owner.id, NOW)

    assert [c.entity_id for c in conditions.values()] == [dropping.id]
    condition = next(iter(conditions.values()))
    assert condition.severity == "critical"  # -60 % is beyond twice the threshold
    assert condition.href == f"/clients/{dropping.id}"
    assert "400" in condition.message and "1.000" in condition.message and "-60,0 %" in condition.message


async def test_recipients_are_admins_and_operational_project_owners_with_client_access(db_session):
    client = await _client(db_session, _summary(700, 1000))
    owner = await _user(db_session)
    finished_owner = await _user(db_session)
    no_access_owner = await _user(db_session, modules=("projects",))
    bystander = await _user(db_session)
    admin = await _user(db_session, role=UserRole.admin, modules=())
    await _own(db_session, client, owner, ProjectStatus.planning)
    await _own(db_session, client, finished_owner, ProjectStatus.completed)
    await _own(db_session, client, no_access_owner)

    received = {
        user.id: bool(await collect_client_conditions(db_session, user.id, NOW))
        for user in (owner, finished_owner, no_access_owner, bystander, admin)
    }
    assert received == {
        owner.id: True, finished_owner.id: False, no_access_owner.id: False,
        bystander.id: False, admin.id: True,
    }
    assert (await collect_client_conditions(db_session, owner.id, NOW))[
        f"{CLIENT_SEO_TRAFFIC_DROP}:client:{client.id}:open"
    ].severity == "warning"


async def test_reconcile_opens_keeps_dismissal_and_resolves_on_recovery(db_session):
    owner = await _user(db_session)
    client = await _client(db_session, _summary(500, 1000))
    await _own(db_session, client, owner)

    await reconcile_recipient(db_session, owner.id, now=NOW)
    [incident] = await _visible(db_session, owner.id)
    assert incident.incident_state == "active" and incident.entity_type == "client"

    incident.incident_state, incident.incident_dismissal_reason = "dismissed", "Migración prevista"
    client.engine_summary_data = _summary(450, 1000)  # next sync, same drop
    await db_session.flush()
    await reconcile_recipient(db_session, owner.id, now=NOW)
    await db_session.refresh(incident)
    assert incident.incident_state == "dismissed"
    assert "450" in incident.message

    client.engine_summary_data = _summary(950, 1000)  # traffic recovered
    await db_session.flush()
    assert await _visible(db_session, owner.id) == []  # live check hides it before the job runs
    await reconcile_recipient(db_session, owner.id, now=NOW)
    await db_session.refresh(incident)
    assert incident.incident_state == "resolved"
    assert incident.incident_resolution_reason == "condition_cleared"


async def test_visibility_follows_live_permission_and_threshold(db_session, monkeypatch):
    owner = await _user(db_session)
    client = await _client(db_session, _summary(700, 1000))
    await _own(db_session, client, owner)
    await reconcile_recipient(db_session, owner.id, now=NOW)
    assert len(await _visible(db_session, owner.id)) == 1

    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 40.0)
    assert await _visible(db_session, owner.id) == []
    assert len(await _visible(db_session, owner.id, current_only=False)) == 1

    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    await db_session.execute(
        UserPermission.__table__.delete().where(UserPermission.user_id == owner.id)
    )
    assert (await db_session.execute(select(Notification.id).where(
        client_visibility_clause(owner.id),
    ))).all() == []


async def test_client_list_sorts_biggest_drops_first_across_pages(db_session, admin_client):
    cohort = uuid4().hex[:8]
    falls = await _client(db_session, _summary(300, 1000), name=f"{cohort} falls")
    dips = await _client(db_session, _summary(900, 1000), name=f"{cohort} dips")
    grows = await _client(db_session, _summary(1500, 1000), name=f"{cohort} grows")
    no_base = await _client(db_session, _summary(50, 0), name=f"{cohort} no base")
    await db_session.commit()
    ours = {falls.id, dips.id, grows.id, no_base.id}

    async def order(sort):
        resp = await admin_client.get("/api/clients", params={"sort": sort, "page_size": 1000})
        assert resp.status_code == 200
        items = resp.json()["items"]
        return [item["id"] for item in items if item["id"] in ours], items

    ids, items = await order("seo_change_asc")
    assert ids == [falls.id, dips.id, grows.id, no_base.id]  # no base always last
    first = next(item for item in items if item["id"] == falls.id)
    assert first["seo_trend"] == "drop_alert" and first["seo_clicks_change_pct"] == -70.0
    assert (await order("seo_change_desc"))[0] == [grows.id, dips.id, falls.id, no_base.id]
    assert (await admin_client.get("/api/clients", params={"sort": "bogus"})).status_code == 422


@pytest.mark.parametrize("summary", [
    {"clicks_30d": "abc", "clicks_previous_30d": 1000},
    {"clicks_30d": 400, "clicks_previous_30d": ""},
    {"clicks_30d": True, "clicks_previous_30d": {"v": 1000}},
    {"clicks_30d": None, "clicks_previous_30d": [1000]},
    {},
])
async def test_drop_clause_never_casts_a_non_numeric_value(db_session, summary):
    """Whatever order Postgres picks, a non-numeric value is "no drop", not an error."""
    from sqlalchemy import cast, literal, not_
    from sqlalchemy.dialects.postgresql import JSONB

    from backend.services.seo_traffic import traffic_drop_clause

    clause = traffic_drop_clause(cast(literal(summary, JSONB), JSONB))
    assert (await db_session.execute(select(clause))).scalar_one() is False
    assert (await db_session.execute(select(not_(clause)))).scalar_one() is True
    client = await _client(db_session, summary)
    assert (await db_session.execute(select(Client.id).where(
        Client.id == client.id, traffic_drop_clause(Client.engine_summary_data),
    ))).all() == []
