"""Importaciones únicas de The Engine contra Postgres real (CSV sintéticos de
`tests/fixtures/engine/`): simulacro sin escribir nada, repetir da lo mismo,
nunca pisa meses/días propios de The Agency, la retención de 16 meses respeta
lo importado y la poda/purga lo borra."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.core.security import encrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, Ga4LeadDaily, Ga4PropertySync, GscConnection, GscDetailSync, GscQueryMonthly,
    GscSiteSync,
)
from backend.scripts import import_engine_leads as il
from backend.scripts import import_engine_positions as ip
from backend.services import gsc_detail_service as detail
from backend.services import seo_control

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "engine"
POSITIONS = FIXTURES / "keyword_positions.csv"
LEADS = FIXTURES / "lead_attribution.csv"
SITE = "sc-domain:acme.com"
PID = "311111111"
TODAY = date(2026, 10, 22)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_cache():
    seo_control.clear_cache()
    yield
    seo_control.clear_cache()


async def _client(db, *, gsc_url=SITE, prop=PID, events=("generate_lead_*",), status=ClientStatus.active):
    client = Client(name="Sage", status=status, gsc_url=gsc_url, ga4_property_id=prop,
                    ga4_lead_events=list(events))
    db.add(client)
    await db.flush()
    return client


async def _monthly(db):
    rows = (await db.execute(select(GscQueryMonthly).order_by(GscQueryMonthly.month, GscQueryMonthly.query))).scalars()
    return {(r.query, r.month): (r.clicks, r.impressions, r.weighted_position_sum, r.source) for r in rows}


async def _agency_months(db, site=SITE):
    """The Agency ya tiene (de Google) agosto y septiembre de 2025 y uno reciente."""
    for month, query, clicks in ((date(2025, 8, 1), "tsaf", 50), (date(2025, 9, 1), "otra", 7),
                                 (date(2026, 9, 1), "tsaf", 70)):
        db.add(GscQueryMonthly(site_url=site, month=month, query=query, clicks=clicks, impressions=100,
                               weighted_position_sum=200.0))
    await db.flush()


# ── Posiciones ───────────────────────────────────────────────────────


async def test_posiciones_simulacro_no_escribe_nada(db_session):
    client = await _client(db_session)
    await _agency_months(db_session)
    await db_session.commit()  # el simulacro deshace su transacción, no lo que ya había
    before = await _monthly(db_session)

    report = await ip.run_import(db_session, POSITIONS, client_id=client.id, dry_run=True)

    assert report.months_imported == [date(2024, 12, 1), date(2025, 1, 1), date(2025, 2, 1), date(2025, 7, 1)]
    assert report.rows_written == 5
    db_session.expire_all()
    assert await _monthly(db_session) == before
    assert "SIMULACRO" in ip.format_report(report)


async def test_posiciones_solo_meses_anteriores_a_los_de_the_agency_y_repetir_da_lo_mismo(db_session):
    client = await _client(db_session)
    await _agency_months(db_session)

    report = await ip.run_import(db_session, POSITIONS, client_id=client.id)

    assert report.agency_first_month == date(2025, 8, 1)
    assert report.months_owned_by_agency == [date(2025, 8, 1), date(2025, 9, 1)]
    assert report.months_incomplete == [date(2025, 10, 1)]
    after = await _monthly(db_session)
    assert after[("tsaf", date(2024, 12, 1))] == (2, 10, 40.0, "engine")
    assert after[("tsaf a distancia", date(2024, 12, 1))] == (1, 30, 300.0, "engine")
    assert after[("tsaf", date(2025, 1, 1))] == (6, 40, 200.0, "engine")
    assert after[("botas", date(2025, 7, 1))] == (4, 50, 250.0, "engine")
    # Los meses de The Agency siguen intactos y el mes incompleto no entra.
    assert after[("tsaf", date(2025, 8, 1))] == (50, 100, 200.0, "google")
    assert ("tsaf", date(2025, 9, 1)) not in after and ("tsaf", date(2025, 10, 1)) not in after

    again = await ip.run_import(db_session, POSITIONS, client_id=client.id)
    assert again.rows_written == report.rows_written == 5
    assert await _monthly(db_session) == after


async def test_posiciones_sin_meses_de_the_agency_importa_todo_lo_completo_y_avisa(db_session):
    client = await _client(db_session)
    report = await ip.run_import(db_session, POSITIONS, client_id=client.id)
    assert report.agency_first_month is None
    assert report.months_imported[-1] == date(2025, 9, 1)
    assert "AVISO" in ip.format_report(report)


@pytest.mark.parametrize("case", ["no_client", "antiguo", "sin_propiedad", "otra_propiedad"])
async def test_posiciones_abortan_sin_cliente_activo_con_esa_web(db_session, case):
    status = ClientStatus.finished if case == "antiguo" else ClientStatus.active
    client = await _client(db_session, gsc_url=None if case == "sin_propiedad" else SITE, status=status)
    kwargs = {"client_id": 999999 if case == "no_client" else client.id}
    if case == "otra_propiedad":
        kwargs["site_url"] = "sc-domain:otra.com"
    with pytest.raises(ip.ImportAborted):
        await ip.run_import(db_session, POSITIONS, **kwargs)
    assert await _monthly(db_session) == {}


async def test_la_retencion_respeta_lo_importado_y_la_poda_lo_borra_con_la_web(db_session):
    client = await _client(db_session)
    await _agency_months(db_session)
    # Un mes viejo de Google (fuera de los 16 meses) sí caduca.
    db_session.add(GscQueryMonthly(site_url=SITE, month=date(2025, 6, 1), query="vieja", clicks=1, impressions=1,
                                   weighted_position_sum=1.0))
    await db_session.flush()
    await ip.run_import(db_session, POSITIONS, client_id=client.id)

    await detail.prune(db_session, today=TODAY)
    months = await _monthly(db_session)
    assert ("vieja", date(2025, 6, 1)) not in months
    assert months[("tsaf", date(2024, 12, 1))][3] == "engine"

    # Cliente Antiguo: la web ya no se sigue y se borra todo, importado incluido.
    client.status = ClientStatus.finished
    await db_session.flush()
    await detail.prune(db_session, today=TODAY)
    assert await _monthly(db_session) == {}


async def test_purgar_la_cuenta_borra_tambien_lo_importado(admin_client, db_session):
    client = await _client(db_session)
    connection = GscConnection(google_email="a@magnify.ing", refresh_token=encrypt_vault_secret("t"),
                               status="connected", connected_at=datetime.now(UTC))
    db_session.add(connection)
    await db_session.flush()
    db_session.add(GscSiteSync(site_url=SITE, connection_id=connection.id))
    await db_session.flush()
    await ip.run_import(db_session, POSITIONS, client_id=client.id)
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{connection.id}/disconnect", json={"purge_data": True})

    assert resp.status_code == 200
    db_session.expire_all()
    assert await _monthly(db_session) == {}


async def test_google_sustituye_un_mes_importado_dentro_de_su_ventana(db_session):
    client = await _client(db_session)
    await ip.run_import(db_session, POSITIONS, client_id=client.id)  # sin meses propios: entra septiembre
    assert (await _monthly(db_session))[("tsaf", date(2025, 9, 1))][3] == "engine"
    await detail.rollup_months(db_session, SITE, [date(2025, 9, 1)])
    months = await _monthly(db_session)
    assert ("tsaf", date(2025, 9, 1)) not in months  # el resumen de Google reemplaza el mes entero


async def test_el_historial_de_una_consulta_ensena_los_meses_importados(admin_client, db_session):
    client = await _client(db_session)
    now = datetime.now(UTC)
    end = date(2026, 10, 18)
    db_session.add(GscSiteSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=end))
    db_session.add(GscDetailSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=end,
                                 monthly_backfilled_at=now))
    await _agency_months(db_session)
    await ip.run_import(db_session, POSITIONS, client_id=client.id)
    await db_session.flush()

    body = (await admin_client.get(f"/api/clients/{client.id}/seo/queries/history",
                                   params={"query": "tsaf"})).json()

    months = {m["month"]: m for m in body["months"]}
    assert months["2024-12-01"]["position"] == 4.0 and months["2024-12-01"]["imported"] is True
    assert months["2025-01-01"]["position"] == 5.0
    assert months["2025-08-01"]["imported"] is False and months["2025-08-01"]["clicks"] == 50
    assert months["2026-09-01"]["clicks"] == 70


# ── Leads ────────────────────────────────────────────────────────────


async def _leads(db):
    rows = (await db.execute(select(Ga4LeadDaily).order_by(Ga4LeadDaily.date, Ga4LeadDaily.landing_page))).scalars()
    return [(r.property_id, r.date, r.landing_page, r.channel, r.leads) for r in rows]


async def _agency_leads(db, since=date(2026, 6, 1)):
    db.add(Ga4PropertySync(property_id=PID, leads_backfilled_at=datetime.now(UTC),
                           leads_events='["generate_lead_*"]', leads_synced_through=date(2026, 10, 21),
                           leads_covered_from=since))
    db.add(Ga4LeadDaily(property_id=PID, date=date(2026, 9, 1), landing_page="acme.com/cpe/",
                        channel="Organic Search", leads=2))
    await db.flush()


async def test_leads_simulacro_no_escribe_nada(db_session):
    await _client(db_session)
    await _agency_leads(db_session)
    await db_session.commit()  # el simulacro deshace su transacción, no lo que ya había
    before = await _leads(db_session)

    report = await il.run_import(db_session, LEADS, property_id=PID, dry_run=True, today=TODAY)

    assert (report.days_imported, report.rows_written, report.leads_written) == (2, 3, 10)
    db_session.expire_all()
    assert await _leads(db_session) == before


async def test_leads_solo_dias_anteriores_a_the_agency_y_repetir_da_lo_mismo(db_session):
    await _client(db_session)
    await _agency_leads(db_session)

    report = await il.run_import(db_session, LEADS, property_id=PID, today=TODAY)

    assert (report.rows_read, report.rows_skipped, report.rows_other_events) == (9, 2, 1)
    assert (report.days_owned_by_agency, report.days_beyond_retention, report.days_imported) == (1, 1, 2)
    rows = await _leads(db_session)
    assert rows == [
        (PID, date(2025, 8, 10), "acme.com/cpe/", "Organic Search", 1),
        (PID, date(2025, 8, 10), "go.acme.com/cpe/", "Paid Search", 5),
        (PID, date(2025, 8, 11), "/blog/x/?ref=1", "(not set)", 4),
        # El día de The Agency no se toca (Engine traía 9 ese día).
        (PID, date(2026, 9, 1), "acme.com/cpe/", "Organic Search", 2),
    ]
    await il.run_import(db_session, LEADS, property_id="properties/" + PID, today=TODAY)
    assert await _leads(db_session) == rows

    # Lo importado está dentro de la retención: la poda no lo toca.
    from backend.services import ga4_leads
    await ga4_leads.prune(db_session, today=TODAY)
    assert await _leads(db_session) == rows


async def test_leads_sin_importacion_de_the_agency_entran_todos_los_dias_y_avisa(db_session):
    await _client(db_session)
    report = await il.run_import(db_session, LEADS, property_id=PID, today=TODAY)
    assert report.days_imported == 3 and "AVISO" in il.format_report(report)


async def test_leads_abortan_sin_cliente_activo_con_esa_propiedad(db_session):
    await _client(db_session, status=ClientStatus.finished)
    with pytest.raises(il.ImportAborted):
        await il.run_import(db_session, LEADS, property_id=PID, today=TODAY)
    with pytest.raises(il.ImportAborted):
        await il.run_import(db_session, LEADS, property_id="G-123", today=TODAY)
    assert await _leads(db_session) == []
