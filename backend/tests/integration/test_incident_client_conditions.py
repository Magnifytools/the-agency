"""Incidencia de caída SEO y semáforo de la lista desde gsc_daily propio, contra Postgres real."""
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, GscDaily, GscSiteSync, Notification, Project, ProjectStatus, User,
    UserPermission, UserRole,
)
from backend.services.gsc_service import normalize_site_url
from backend.services.incident_client_conditions import (
    CLIENT_SEO_TRAFFIC_DROP, client_visibility_clause, collect_client_conditions,
)
from backend.services.incidents import reconcile_recipient, visible_incident_clause

NOW = datetime(2026, 10, 18, 9)  # noqa: DTZ001 - application stores naive UTC
LAST = date(2026, 10, 16)
START = LAST - timedelta(days=27)  # primer día de la ventana compartida (28 días)

# Un resumen de Engine que sería una caída: ya no debe contar para nada.
ENGINE_DROP = {
    "clicks_30d": 10, "clicks_previous_30d": 1000,
    "impressions_30d": 1, "impressions_previous_30d": 1, "as_of": "2026-10-17",
}


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 100)


async def _gsc(db, site, clicks, previous, impressions=(9000, 10000), backfilled=True):
    """Un día dentro de la ventana y otro en los 28 anteriores; devuelve ambos."""
    db.add(GscSiteSync(site_url=site, backfilled_at=datetime.now(UTC) if backfilled else None,
                       last_data_date=LAST))
    recent = GscDaily(site_url=site, date=START, clicks=clicks, impressions=impressions[0], position=5.0)
    before = GscDaily(site_url=site, date=START - timedelta(days=1), clicks=previous,
                      impressions=impressions[1], position=5.0)
    db.add_all([recent, before])
    await db.flush()
    return recent, before


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


_UNSET = object()


async def _client(db, traffic=None, gsc_url=_UNSET, **fields):
    """Cliente con su propiedad de Search Console y (clics, anteriores) en la ventana."""
    site = f"sc-domain:{uuid4().hex[:12]}.es" if gsc_url is _UNSET else gsc_url
    client = Client(name=fields.pop("name", f"SEO client {uuid4().hex[:8]}"), gsc_url=site, **fields)
    db.add(client)
    await db.flush()
    if traffic is not None:
        await _gsc(db, normalize_site_url(site), *traffic)
    return client


async def _own(db, client, owner, status=ProjectStatus.active):
    db.add(Project(name="SEO", client_id=client.id, owner_id=owner.id, status=status))
    await db.flush()


async def _visible(db, user_id, current_only=True):
    return (await db.execute(select(Notification).where(
        Notification.type == CLIENT_SEO_TRAFFIC_DROP,
        visible_incident_clause(user_id, current_only=current_only),
    ))).scalars().all()


async def test_only_real_drops_on_active_clients_with_own_data_raise_a_condition(db_session):
    owner = await _user(db_session)
    dropping = await _client(db_session, (400, 1000))
    # Se escribe a mano sin barra final: se normaliza igual que la importación.
    url_typed = await _client(db_session, (400, 1000), gsc_url=f" https://{uuid4().hex[:8]}.es ")
    unsynced = await _client(db_session)
    await _gsc(db_session, unsynced.gsc_url, 400, 1000, backfilled=False)  # sin histórico importado
    for client in [
        dropping,
        url_typed,
        unsynced,
        await _client(db_session, (850, 1000)),                      # -15 %: bajo el umbral
        await _client(db_session, (10, 90)),                         # poco volumen
        await _client(db_session, (400, 1000), status=ClientStatus.paused),
        await _client(db_session, (400, 1000), is_internal=True),
        await _client(db_session, None),                             # propiedad sin datos
        await _client(db_session, None, gsc_url=None),
        # The Engine está congelado: su resumen ya no abre incidencias.
        await _client(db_session, None, gsc_url=None, engine_project_id=7, engine_summary_data=ENGINE_DROP),
    ]:
        await _own(db_session, client, owner)

    conditions = await collect_client_conditions(db_session, owner.id, NOW)

    assert [c.entity_id for c in conditions.values()] == [dropping.id, url_typed.id]
    condition = conditions[f"{CLIENT_SEO_TRAFFIC_DROP}:client:{dropping.id}:open"]
    assert condition.severity == "critical"  # -60 % es más del doble del umbral
    assert condition.href == f"/clients/{dropping.id}"
    assert "400" in condition.message and "1.000" in condition.message and "-60,0 %" in condition.message
    assert "28 días" in condition.message and "16/10/2026" in condition.message
    assert "Impresiones: -10,0 %" in condition.message and "Engine" not in condition.message


async def test_recipients_are_admins_and_operational_project_owners_with_client_access(db_session):
    client = await _client(db_session, (700, 1000))
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
    site = f"sc-domain:{uuid4().hex[:12]}.es"
    client = await _client(db_session, None, gsc_url=site)
    recent, _ = await _gsc(db_session, site, 500, 1000)
    await _own(db_session, client, owner)

    await reconcile_recipient(db_session, owner.id, now=NOW)
    [incident] = await _visible(db_session, owner.id)
    assert incident.incident_state == "active" and incident.entity_type == "client"

    incident.incident_state, incident.incident_dismissal_reason = "dismissed", "Migración prevista"
    recent.clicks = 450  # siguiente importación, la misma caída
    await db_session.flush()
    await reconcile_recipient(db_session, owner.id, now=NOW)
    await db_session.refresh(incident)
    assert incident.incident_state == "dismissed"
    assert "450" in incident.message

    recent.clicks = 950  # el tráfico se recupera
    await db_session.flush()
    assert await _visible(db_session, owner.id) == []  # la comprobación en vivo la oculta ya
    await reconcile_recipient(db_session, owner.id, now=NOW)
    await db_session.refresh(incident)
    assert incident.incident_state == "resolved"
    assert incident.incident_resolution_reason == "condition_cleared"


async def test_visibility_follows_live_permission_and_threshold(db_session, monkeypatch):
    owner = await _user(db_session)
    client = await _client(db_session, (700, 1000))
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
    falls = await _client(db_session, (300, 1000), name=f"{cohort} falls")
    dips = await _client(db_session, (900, 1000), name=f"{cohort} dips")
    grows = await _client(db_session, (1500, 1000), name=f"{cohort} grows")
    no_base = await _client(db_session, (50, 0), name=f"{cohort} no base")
    no_site = await _client(db_session, None, gsc_url=None, name=f"{cohort} no site",
                            engine_project_id=7, engine_summary_data=ENGINE_DROP)
    await db_session.commit()
    ours = {falls.id, dips.id, grows.id, no_base.id, no_site.id}

    async def order(sort):
        resp = await admin_client.get("/api/clients", params={"sort": sort, "page_size": 1000})
        assert resp.status_code == 200
        items = resp.json()["items"]
        return [item["id"] for item in items if item["id"] in ours], items

    ids, items = await order("seo_change_asc")
    # Sin base o sin propiedad, siempre al final (luego por alta, la más nueva antes).
    assert ids == [falls.id, dips.id, grows.id, no_site.id, no_base.id]
    by_id = {item["id"]: item for item in items}
    assert by_id[falls.id]["seo_trend"] == "drop_alert" and by_id[falls.id]["seo_clicks_change_pct"] == -70.0
    assert by_id[falls.id]["seo_impressions_change_pct"] == -10.0
    assert by_id[no_site.id]["seo_trend"] is None  # el resumen de Engine ya no cuenta
    assert (await order("seo_change_desc"))[0] == [grows.id, dips.id, falls.id, no_site.id, no_base.id]

    # El orden por defecto también trae el semáforo, y la ficha igual.
    _, default_items = await order("created")
    assert next(i for i in default_items if i["id"] == grows.id)["seo_trend"] == "up"
    detail = (await admin_client.get(f"/api/clients/{dips.id}")).json()
    assert detail["seo_trend"] == "down" and detail["seo_clicks_change_pct"] == -10.0
    assert (await admin_client.get("/api/clients", params={"sort": "bogus"})).status_code == 422


async def test_window_matches_client_status_to_the_day(db_session):
    """Semáforo, incidencia y estado usan la misma ventana de 28 + 28 días."""
    from backend.services.client_status import Viewer, portfolio
    from backend.services.seo_control import seo_window
    from backend.services.seo_traffic import traffic_by_client

    site = f"sc-domain:{uuid4().hex[:12]}.es"
    client = await _client(db_session, None, gsc_url=site)
    db_session.add(GscSiteSync(site_url=site, backfilled_at=datetime.now(UTC), last_data_date=LAST))
    window = seo_window(LAST)
    days = {
        window.end + timedelta(days=1): 10_000,              # después del último día final: fuera
        window.end: 1, window.start: 2,                       # ventana actual
        window.previous_end: 40, window.previous_start: 80,   # los 28 anteriores
        window.previous_start - timedelta(days=1): 10_000,    # antes: fuera
    }
    db_session.add_all([GscDaily(site_url=site, date=d, clicks=c, impressions=c, position=1.0)
                        for d, c in days.items()])
    await db_session.flush()

    traffic = (await traffic_by_client(db_session, [client.id]))[client.id]
    assert (traffic.clicks, traffic.clicks_previous, traffic.as_of) == (3, 120, LAST)
    viewer = Viewer(is_admin=True, tasks=False, digests=False, timesheet=False)
    row = (await portfolio(db_session, [client], viewer))[0]
    assert row["seo"]["clicks"] == 3 and row["seo"]["clicks_previous"] == 120
    assert row["seo"]["change_pct"] == traffic.clicks_change_pct == -97.5
