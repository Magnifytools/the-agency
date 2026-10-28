"""Desconectar Google de verdad y retención de eventos importados, contra Postgres real.

La revocación en Google la sustituye el fixture autouse ``_no_real_google_revoke``
(backend/tests/conftest.py): aquí sólo se mira con qué token se llama.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.core.security import encrypt_vault_secret
from backend.db.models import (
    Event, EventType, Ga4Daily, Ga4PropertySync, GscConnection, GscDaily, GscSiteSync, User,
)
from backend.services.google_calendar_service import purge_past_google_events

pytestmark = pytest.mark.integration


async def _connection(db, email: str, token: str) -> int:
    connection = GscConnection(google_email=email, refresh_token=encrypt_vault_secret(token),
                               status="connected", connected_at=datetime.now(UTC))
    db.add(connection)
    await db.flush()
    return connection.id


async def _imported(db, connection_id: int, *, site: str, prop: str) -> None:
    db.add_all([
        GscSiteSync(site_url=site, connection_id=connection_id, last_data_date=date(2026, 10, 18)),
        GscDaily(site_url=site, date=date(2026, 10, 17), clicks=5, impressions=50, position=4.0),
        GscDaily(site_url=site, date=date(2026, 10, 18), clicks=6, impressions=60, position=3.0),
        Ga4PropertySync(property_id=prop, connection_id=connection_id, last_data_date=date(2026, 10, 18)),
        Ga4Daily(property_id=prop, date=date(2026, 10, 18), sessions=10, key_events=1.0,
                 ai_sessions=1, ai_key_events=0.0),
    ])
    await db.flush()


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


async def test_desconectar_sin_purgar_revoca_y_conserva_las_cifras(admin_client, db_session, _no_real_google_revoke):
    mine = await _connection(db_session, "a@magnify.ing", "token-a")
    await _imported(db_session, mine, site="sc-domain:a.com", prop="111")
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine}/disconnect")

    assert resp.status_code == 200
    assert resp.json() == {"status": "disconnected", "google_revoked": True, "purged": None}
    _no_real_google_revoke.assert_awaited_once_with("token-a")
    db_session.expire_all()
    assert await db_session.get(GscConnection, mine) is None
    assert await _count(db_session, GscDaily) == 2
    assert await _count(db_session, Ga4Daily) == 1
    # Sin cuenta: el estado se queda para la siguiente cuenta que vea la propiedad.
    assert (await db_session.get(GscSiteSync, "sc-domain:a.com")).connection_id is None


async def test_desconectar_purgando_borra_solo_las_propiedades_de_esa_cuenta(admin_client, db_session):
    mine = await _connection(db_session, "a@magnify.ing", "token-a")
    other = await _connection(db_session, "b@magnify.ing", "token-b")
    await _imported(db_session, mine, site="sc-domain:a.com", prop="111")
    await _imported(db_session, other, site="sc-domain:b.com", prop="222")
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine}/disconnect", json={"purge_data": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["google_revoked"] is True
    assert body["purged"] == {"gsc_sites": 1, "gsc_rows": 2, "gsc_query_rows": 0, "gsc_page_rows": 0,
                              "ga4_properties": 1, "ga4_rows": 1}
    db_session.expire_all()
    assert await _count(db_session, GscDaily, GscDaily.site_url == "sc-domain:a.com") == 0
    assert await db_session.get(GscSiteSync, "sc-domain:a.com") is None
    assert await _count(db_session, Ga4Daily, Ga4Daily.property_id == "111") == 0
    assert await db_session.get(Ga4PropertySync, "111") is None
    # La otra cuenta y sus cifras, intactas.
    assert await db_session.get(GscConnection, other) is not None
    assert await _count(db_session, GscDaily, GscDaily.site_url == "sc-domain:b.com") == 2
    assert (await db_session.get(GscSiteSync, "sc-domain:b.com")).connection_id == other
    assert await _count(db_session, Ga4Daily, Ga4Daily.property_id == "222") == 1
    assert (await db_session.get(Ga4PropertySync, "222")).connection_id == other


async def test_si_google_no_confirma_se_desconecta_igual_y_se_dice(admin_client, db_session, _no_real_google_revoke):
    _no_real_google_revoke.return_value = False
    mine = await _connection(db_session, "a@magnify.ing", "token-a")
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine}/disconnect", json={"purge_data": False})

    assert resp.status_code == 200
    assert resp.json()["google_revoked"] is False
    db_session.expire_all()
    assert await db_session.get(GscConnection, mine) is None


async def test_desconectar_gsc_es_solo_de_admin(member_client, db_session):
    mine = await _connection(db_session, "a@magnify.ing", "token-a")
    await db_session.commit()
    assert (await member_client.post(f"/api/gsc/connections/{mine}/disconnect", json={"purge_data": True})).status_code == 403


def _event(user_id: int, title: str, *, source: str, start: datetime, end: datetime | None = None,
           google_event_id: str | None = None) -> Event:
    return Event(user_id=user_id, title=title, event_type=EventType.meeting, source=source,
                 google_event_id=google_event_id, source_calendar_id="primary" if source == "google" else None,
                 start_time=start, end_time=end)


async def test_desconectar_calendar_borra_solo_los_eventos_de_google_de_esa_persona(
    member_client, admin_user, db_session, _no_real_google_revoke,
):
    me = member_client.test_user
    my_id = me.id
    me.google_refresh_token = encrypt_vault_secret("cal-token")
    me.google_calendar_id = "primary"
    me.google_calendar_connected = True
    start = datetime(2026, 10, 22, 10)
    db_session.add_all([
        _event(me.id, "Mía de Google", source="google", start=start, google_event_id="g1"),
        _event(me.id, "Mía de Google 2", source="google", start=start, google_event_id="g2"),
        _event(me.id, "Mía manual", source="manual", start=start),
        _event(admin_user.id, "De otro, de Google", source="google", start=start, google_event_id="g1"),
    ])
    await db_session.commit()

    resp = await member_client.post("/api/calendar/disconnect")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "google_revoked": True, "events_deleted": 2, "blocks_calendar_deleted": False}
    _no_real_google_revoke.assert_awaited_once_with("cal-token")
    db_session.expire_all()
    titles = set((await db_session.scalars(select(Event.title))).all())
    assert titles == {"Mía manual", "De otro, de Google"}
    user = await db_session.get(User, my_id)
    assert user.google_refresh_token is None and user.google_calendar_connected is False


async def test_desconectar_calendar_sin_token_no_llama_a_google(member_client, db_session, _no_real_google_revoke):
    resp = await member_client.post("/api/calendar/disconnect")

    assert resp.status_code == 200
    assert resp.json()["google_revoked"] is False
    _no_real_google_revoke.assert_not_awaited()


async def test_retencion_borra_solo_eventos_de_google_terminados_hace_mas_de_30_dias(admin_user, db_session):
    now = datetime(2026, 10, 21, 12)
    uid = admin_user.id
    db_session.add_all([
        _event(uid, "Google viejo", source="google", google_event_id="old",
               start=now - timedelta(days=40), end=now - timedelta(days=40, hours=-1)),
        _event(uid, "Google viejo sin fin", source="google", google_event_id="old-nofin",
               start=now - timedelta(days=31)),
        _event(uid, "Google empezó hace 31 y terminó hace 29", source="google", google_event_id="long",
               start=now - timedelta(days=31), end=now - timedelta(days=29)),
        _event(uid, "Google reciente", source="google", google_event_id="recent",
               start=now - timedelta(days=5), end=now - timedelta(days=5, hours=-1)),
        _event(uid, "Manual viejo", source="manual",
               start=now - timedelta(days=200), end=now - timedelta(days=200, hours=-1)),
    ])
    await db_session.flush()

    deleted = await purge_past_google_events(db_session, now=now)

    assert deleted == 2
    titles = set((await db_session.scalars(select(Event.title))).all())
    assert titles == {"Google empezó hace 31 y terminó hace 29", "Google reciente", "Manual viejo"}
