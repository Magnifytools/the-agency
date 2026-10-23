"""Leads por landing de GA4 contra Postgres real: importación (16 meses, cola,
cambio de eventos), retención, poda de propiedades sin cliente, purga al
desconectar, API de la ficha y edición de los eventos."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.core.security import encrypt_vault_secret
from backend.db.models import Client, ClientStatus, Ga4Daily, Ga4LeadDaily, Ga4PropertySync, GscConnection
from backend.services import ga4_leads, ga4_service
from backend.services.ga4_leads import LeadRow
from backend.services.ga4_service import Ga4Error, Ga4Row

pytestmark = pytest.mark.integration

PID = "311111111"
TODAY = date(2026, 10, 22)
YESTERDAY = TODAY - timedelta(days=1)
FLOOR = date(2025, 7, 1)


def _factory(db):
    @asynccontextmanager
    async def factory():
        yield db
    return factory


async def _connect(db, email="digital@magnify.ing", token="v1:a"):
    c = GscConnection(google_email=email, refresh_token=token, status="connected", connected_at=datetime.now(UTC))
    db.add(c)
    await db.flush()
    return c


async def _client(db, prop=PID, name="Fit", events=None, status=ClientStatus.active):
    c = Client(name=name, status=status, ga4_property_id=prop, ga4_lead_events=events or ["generate_lead"])
    db.add(c)
    await db.flush()
    return c


async def _list_fn(_token):
    return [PID]


async def _daily(_token, _pid, _start, end):
    return [Ga4Row(end, 10, 1.0, 0, 0.0)]


async def _leads(db, pid=PID):
    rows = (await db.execute(select(Ga4LeadDaily).where(Ga4LeadDaily.property_id == pid)
                             .order_by(Ga4LeadDaily.date, Ga4LeadDaily.landing_page))).scalars().all()
    return [(r.date, r.landing_page, r.channel, r.leads) for r in rows]


# ── Importación ──────────────────────────────────────────────────────


async def test_primera_vez_16_meses_luego_la_cola_y_si_cambian_los_eventos_otra_vez_todo(db_session):
    await _connect(db_session)
    client = await _client(db_session, events=["generate_lead_*"])
    calls = []

    async def fetch_leads(token, pid, start, end, events):
        calls.append((start, end, tuple(events)))
        return [LeadRow(end, "acme.com/cpe/", "Paid Search", 3), LeadRow(start, "acme.com/", "Organic Search", 1)]

    result = await ga4_service.sync_all(_factory(db_session), fetch=_daily, list_fn=_list_fn,
                                        fetch_leads=fetch_leads, today=TODAY)
    assert result == {"status": "ok", "synced": 1, "failed": 0, "leads_failed": 0}
    # 486 días hacia atrás, pero nunca antes de la retención (julio de 2025).
    assert calls[-1] == (FLOOR, YESTERDAY, ("generate_lead_*",))
    state = await db_session.get(Ga4PropertySync, PID)
    assert state.leads_synced_through == YESTERDAY and state.leads_covered_from == FLOOR
    assert state.leads_backfilled_at is not None and state.leads_events == '["generate_lead_*"]'
    assert len(await _leads(db_session)) == 2

    # Al día siguiente: sólo la última semana, y sustituye el tramo.
    await ga4_service.sync_all(_factory(db_session), fetch=_daily, list_fn=_list_fn,
                               fetch_leads=fetch_leads, today=TODAY + timedelta(days=1))
    assert calls[-1][:2] == (YESTERDAY - timedelta(days=7), TODAY)
    assert (await db_session.get(Ga4PropertySync, PID)).leads_covered_from == FLOOR

    # Cambian los eventos: vuelve a importar todo con los nuevos.
    client.ga4_lead_events = ["generate_lead"]
    await db_session.flush()
    await ga4_service.sync_all(_factory(db_session), fetch=_daily, list_fn=_list_fn,
                               fetch_leads=fetch_leads, today=TODAY + timedelta(days=1))
    assert calls[-1] == (FLOOR, TODAY, ("generate_lead",))


async def test_la_cola_sustituye_las_filas_que_ya_no_salen(db_session):
    await _client(db_session)
    now = datetime.now(UTC)
    db_session.add(Ga4PropertySync(property_id=PID, leads_backfilled_at=now, leads_events='["generate_lead"]',
                                   leads_synced_through=YESTERDAY - timedelta(days=1), leads_covered_from=FLOOR))
    db_session.add_all([
        Ga4LeadDaily(property_id=PID, date=YESTERDAY - timedelta(days=2), landing_page="/viejo", channel="x", leads=4),
        Ga4LeadDaily(property_id=PID, date=YESTERDAY - timedelta(days=30), landing_page="/fuera", channel="x", leads=1),
    ])
    await db_session.flush()

    async def fetch(token, pid, start, end, events):
        return [LeadRow(YESTERDAY, "/nuevo", "x", 2)]

    await ga4_leads.sync_property_leads(db_session, "v1:a", PID, ["generate_lead"], fetch=fetch, today=TODAY)
    assert await _leads(db_session) == [
        (YESTERDAY - timedelta(days=30), "/fuera", "x", 1), (YESTERDAY, "/nuevo", "x", 2)]


async def test_un_fallo_de_los_leads_no_tumba_los_totales(db_session):
    await _connect(db_session)
    await _client(db_session)

    async def broken(*_args):
        raise Ga4Error("rate_limited")

    result = await ga4_service.sync_all(_factory(db_session), fetch=_daily, list_fn=_list_fn,
                                        fetch_leads=broken, today=TODAY)
    assert result == {"status": "ok", "synced": 1, "failed": 0, "leads_failed": 1}
    assert await db_session.get(Ga4Daily, (PID, YESTERDAY)) is not None
    state = await db_session.get(Ga4PropertySync, PID)
    assert state.leads_error_code == "rate_limited" and state.leads_backfilled_at is None


async def test_dos_clientes_con_la_misma_propiedad_suman_sus_eventos(db_session):
    await _client(db_session, events=["generate_lead"])
    await _client(db_session, name="Otro", events=["form_*", "generate_lead"])
    await _client(db_session, prop="999999999", name="Antiguo", status=ClientStatus.finished)
    assert await ga4_leads.property_lead_events(db_session) == {PID: ["form_*", "generate_lead"]}


# ── Retención y borrado ──────────────────────────────────────────────


async def test_retencion_16_meses_y_poda_de_propiedades_sin_cliente(db_session):
    await _client(db_session)
    await _client(db_session, prop="322222222", name="Antiguo", status=ClientStatus.finished)
    db_session.add(Ga4PropertySync(property_id="322222222", leads_events='["generate_lead"]',
                                   leads_backfilled_at=datetime.now(UTC), leads_synced_through=YESTERDAY))
    db_session.add_all([
        Ga4LeadDaily(property_id=PID, date=FLOOR - timedelta(days=1), landing_page="/a", channel="x", leads=1),
        Ga4LeadDaily(property_id=PID, date=FLOOR, landing_page="/a", channel="x", leads=1),
        Ga4LeadDaily(property_id="322222222", date=YESTERDAY, landing_page="/a", channel="x", leads=1),
    ])
    await db_session.flush()

    await ga4_leads.prune(db_session, today=TODAY)

    assert [(r.property_id, r.date) for r in (await db_session.scalars(select(Ga4LeadDaily))).all()] == [
        (PID, FLOOR)]
    stale = await db_session.get(Ga4PropertySync, "322222222")
    assert stale.leads_events is None and stale.leads_backfilled_at is None and stale.leads_synced_through is None


async def test_desconectar_purgando_borra_tambien_los_leads(admin_client, db_session):
    mine = await _connect(db_session, "a@magnify.ing", encrypt_vault_secret("token-a"))
    other = await _connect(db_session, "b@magnify.ing", encrypt_vault_secret("token-b"))
    for pid, cid in ((PID, mine.id), ("322222222", other.id)):
        db_session.add_all([
            Ga4PropertySync(property_id=pid, connection_id=cid, last_data_date=YESTERDAY),
            Ga4LeadDaily(property_id=pid, date=YESTERDAY, landing_page="/a", channel="x", leads=1),
        ])
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine.id}/disconnect", json={"purge_data": True})

    assert resp.status_code == 200
    db_session.expire_all()
    assert set((await db_session.scalars(select(Ga4LeadDaily.property_id))).all()) == {"322222222"}


# ── API de la ficha ──────────────────────────────────────────────────


async def test_leads_de_la_ficha_frente_a_la_ventana_anterior(admin_client, db_session):
    client = await _client(db_session, events=["generate_lead_*"])
    end = date(2026, 10, 18)
    db_session.add(Ga4PropertySync(property_id=PID, leads_backfilled_at=datetime.now(UTC),
                                   leads_events='["generate_lead_*"]', leads_synced_through=end,
                                   leads_covered_from=FLOOR))
    for offset, landing, channel, leads in (
        (0, "acme.com/cpe/", "Paid Search", 6),
        (27, "acme.com/cpe/", "Organic Search", 4),
        (3, "acme.com/blog/", "Organic Search", 2),
        (28, "acme.com/cpe/", "Paid Search", 5),      # ventana anterior
        (40, "acme.com/viejo/", "Referral", 3),       # ventana anterior
        (56, "acme.com/cpe/", "Paid Search", 100),    # fuera de las dos
    ):
        db_session.add(Ga4LeadDaily(property_id=PID, date=end - timedelta(days=offset), landing_page=landing,
                                    channel=channel, leads=leads))
    await db_session.flush()

    body = (await admin_client.get(f"/api/clients/{client.id}/leads")).json()

    assert body["status"] == "ok" and body["events"] == ["generate_lead_*"]
    assert (body["start"], body["end"]) == ("2026-09-21", "2026-10-18")
    assert (body["previous_start"], body["previous_end"]) == ("2026-08-24", "2026-09-20")
    assert body["total"] == {"leads": 12, "previous": 8, "change_pct": 50.0}
    assert body["landings"] == [
        {"landing_page": "acme.com/cpe/", "leads": 10, "previous": 5, "change_pct": 100.0},
        {"landing_page": "acme.com/blog/", "leads": 2, "previous": 0, "change_pct": None},
    ]
    assert body["channels"] == [
        {"channel": "Paid Search", "leads": 6, "previous": 5, "change_pct": 20.0},
        {"channel": "Organic Search", "leads": 6, "previous": 0, "change_pct": None},
        {"channel": "Referral", "leads": 0, "previous": 3, "change_pct": -100.0},
    ]
    week = (await admin_client.get(f"/api/clients/{client.id}/leads", params={"days": 7})).json()
    assert week["total"]["leads"] == 8
    assert (await admin_client.get(f"/api/clients/{client.id}/leads", params={"days": 30})).status_code == 422


async def test_sin_datos_anteriores_no_hay_comparacion(admin_client, db_session):
    client = await _client(db_session)
    end = date(2026, 10, 18)
    db_session.add(Ga4PropertySync(property_id=PID, leads_backfilled_at=datetime.now(UTC),
                                   leads_events='["generate_lead"]', leads_synced_through=end,
                                   leads_covered_from=end - timedelta(days=10)))
    db_session.add(Ga4LeadDaily(property_id=PID, date=end, landing_page="/a", channel="x", leads=2))
    await db_session.flush()
    body = (await admin_client.get(f"/api/clients/{client.id}/leads")).json()
    assert body["comparable"] is False and body["total"] == {"leads": 2, "previous": None, "change_pct": None}


async def test_estados_sin_propiedad_y_sin_importar(admin_client, db_session):
    none = await _client(db_session, prop=None, name="Sin GA4")
    assert (await admin_client.get(f"/api/clients/{none.id}/leads")).json()["status"] == "no_property"
    pending = await _client(db_session, name="Pendiente")
    db_session.add(Ga4PropertySync(property_id=PID, leads_error_code="missing_scope"))
    await db_session.flush()
    body = (await admin_client.get(f"/api/clients/{pending.id}/leads")).json()
    assert body["status"] == "not_synced" and body["error_code"] == "missing_scope"
    assert (await admin_client.get("/api/clients/999999/leads")).status_code == 404


async def test_hace_falta_leer_clientes(member_client, db_session):
    client = await _client(db_session)
    assert (await member_client.get(f"/api/clients/{client.id}/leads")).status_code == 403


async def test_los_eventos_se_editan_y_validan_en_el_cliente(admin_client, db_session):
    client = await _client(db_session)
    url = f"/api/clients/{client.id}"
    assert (await admin_client.get(url)).json()["ga4_lead_events"] == ["generate_lead"]
    resp = await admin_client.put(url, json={"ga4_lead_events": [" generate_lead_* ", "form_enviado"]})
    assert resp.status_code == 200 and resp.json()["ga4_lead_events"] == ["generate_lead_*", "form_enviado"]
    for bad in ([], ["lead-form"], ["a*b"], "generate_lead"):
        assert (await admin_client.put(url, json={"ga4_lead_events": bad})).status_code == 422
    resp = await admin_client.put(url, json={"ga4_lead_events": None})
    assert resp.json()["ga4_lead_events"] == ["generate_lead"]
    # Guardar otro campo no toca los eventos.
    await admin_client.put(url, json={"ga4_lead_events": ["form_*"]})
    assert (await admin_client.put(url, json={"notes": "x"})).json()["ga4_lead_events"] == ["form_*"]
