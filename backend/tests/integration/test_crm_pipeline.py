"""CRM: Pipeline reactivado con historial de etapas, embudo, avisos y entradas."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.core.rate_limiter import public_link_limiter
from backend.db.models import (
    InboxNote, InboxNoteStatus, Lead, LeadSource, LeadStatus, LeadStatusHistory, Notification,
)
from backend.services import lead_pipeline
from backend.services.incidents import reconcile_recipient
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seller(make_member_client):
    client = await make_member_client([("growth", True, True)])
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def anon(app_with_db):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def _fresh_limiter():
    public_link_limiter._limiter._requests.clear()
    yield
    public_link_limiter._limiter._requests.clear()


async def _lead(api, **extra) -> dict:
    r = await api.post("/api/leads", json={"company_name": "Acme", **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def _history(db_session, lead_id: int) -> list[str]:
    return [row.value for row in await db_session.scalars(select(LeadStatusHistory.status).where(
        LeadStatusHistory.lead_id == lead_id).order_by(LeadStatusHistory.id))]


async def test_a_new_lead_records_its_stage_and_tells_admins_but_not_its_creator(admin_client, seller, db_session):
    created = await _lead(seller, contact_name="Ana")
    assert await _history(db_session, created["id"]) == ["new"]
    notes = list(await db_session.scalars(select(Notification).where(Notification.type == "lead_new")))
    assert [n.user_id for n in notes] == [admin_client.test_user.id]
    assert notes[0].title == "Lead nuevo: Acme" and notes[0].link_url == f"/leads/{created['id']}"
    assert "Contacto: Ana" in notes[0].message


async def test_stage_changes_feed_the_funnel(admin_client, db_session):
    ids = [(await _lead(admin_client, company_name=f"L{i}"))["id"] for i in range(4)]
    start = datetime.utcnow() - timedelta(days=20)
    # Fechas controladas: todo empieza hace 20 días.
    for row in await db_session.scalars(select(LeadStatusHistory)):
        row.entered_at = start
    await db_session.commit()
    path = {ids[0]: ["contacted", "discovery", "proposal", "won"], ids[1]: ["contacted", "lost"],
            ids[2]: ["contacted"], ids[3]: []}
    for lead_id, steps in path.items():
        for step in steps:
            r = await admin_client.put(f"/api/leads/{lead_id}", json={"status": step})
            assert r.status_code == 200, r.text
    # El primero estuvo 4 días en "Nuevo".
    first = list(await db_session.scalars(select(LeadStatusHistory).where(
        LeadStatusHistory.lead_id == ids[0]).order_by(LeadStatusHistory.id)))
    first[1].entered_at = start + timedelta(days=4)
    await db_session.commit()

    funnel = (await admin_client.get("/api/leads/funnel", params={"days": 90})).json()
    stages = {stage["status"]: stage for stage in funnel["stages"]}
    assert funnel["total"] == 4 and (funnel["won"], funnel["lost"]) == (1, 1)
    assert funnel["win_rate_pct"] == 50.0
    assert (stages["new"]["reached"], stages["new"]["moved_on"], stages["new"]["conversion_pct"]) == (4, 3, 75.0)
    assert (stages["contacted"]["reached"], stages["contacted"]["moved_on"]) == (3, 1)
    assert stages["won"]["reached"] == 1 and stages["won"]["conversion_pct"] is None
    assert stages["new"]["avg_days"] is not None


async def test_weighted_value_only_counts_open_leads(admin_client):
    await _lead(admin_client, estimated_value=1000, probability=50)
    won = await _lead(admin_client, estimated_value=5000, probability=100)
    await admin_client.put(f"/api/leads/{won['id']}", json={"status": "won"})
    summary = (await admin_client.get("/api/leads/pipeline-summary")).json()
    assert Decimal(str(summary["weighted_value"])) == Decimal("500")


async def test_due_followups_show_in_my_agenda_and_ring_the_bell(seller, admin_client, db_session):
    today = business_today()
    due = await _lead(seller, next_followup_date=(today - timedelta(days=1)).isoformat(),
                      next_followup_notes="Llamar para el presupuesto")
    await _lead(seller, company_name="Más adelante", next_followup_date=(today + timedelta(days=5)).isoformat())
    orphan = await _lead(admin_client, company_name="Sin dueño", assigned_to=None,
                         next_followup_date=today.isoformat())
    await admin_client.put(f"/api/leads/{orphan['id']}", json={"assigned_to": None})

    agenda = (await seller.get("/api/leads/agenda", params={"date": today.isoformat()})).json()
    assert [row["company_name"] for row in agenda] == ["Acme"]
    assert agenda[0]["days_until_followup"] == -1
    admin_agenda = (await admin_client.get("/api/leads/agenda", params={"date": today.isoformat()})).json()
    assert "Sin dueño" in [row["company_name"] for row in admin_agenda]

    await reconcile_recipient(db_session, seller.test_user.id)
    incident = (await db_session.execute(select(Notification).where(
        Notification.user_id == seller.test_user.id, Notification.type == "lead_followup_due"))).scalar_one()
    assert incident.incident_state == "active" and "Llamar para el presupuesto" in incident.message
    await seller.put(f"/api/leads/{due['id']}", json={"next_followup_date": (today + timedelta(days=7)).isoformat()})
    await reconcile_recipient(db_session, seller.test_user.id)
    await db_session.refresh(incident)
    assert incident.incident_state == "resolved"


async def test_an_inbox_note_becomes_a_lead_once(seller, db_session):
    note = InboxNote(user_id=seller.test_user.id, raw_text="Clínica Dental Sol\nQuieren SEO local, llamar el lunes")
    db_session.add(note)
    await db_session.commit()
    r = await seller.post(f"/api/inbox/{note.id}/lead")
    assert r.status_code == 200, r.text
    again = await seller.post(f"/api/inbox/{note.id}/lead")
    assert again.status_code == 200
    leads = list(await db_session.scalars(select(Lead)))
    assert len(leads) == 1 and leads[0].company_name == "Clínica Dental Sol"
    assert leads[0].assigned_to == seller.test_user.id and "llamar el lunes" in leads[0].notes
    await db_session.refresh(note)
    assert (note.status, note.resolved_as, note.resolved_entity_id) == (InboxNoteStatus.processed, "lead", leads[0].id)


async def test_the_web_form_needs_the_token(anon, admin_user, db_session, monkeypatch):
    body = {"company": "Hotel Mar", "name": "Luis", "email": "luis@hotelmar.es", "message": "Presupuesto SEO",
            "page_url": "https://magnify.ing/contacto"}
    assert (await anon.post("/api/leads/inbound", json=body)).status_code == 404
    monkeypatch.setattr(settings, "LEADS_WEBHOOK_TOKEN", "s3creto-del-formulario")
    assert (await anon.post("/api/leads/inbound", json=body, headers={"X-Lead-Token": "otro"})).status_code == 404
    ok = await anon.post("/api/leads/inbound", json=body, headers={"X-Lead-Token": "s3creto-del-formulario"})
    assert ok.status_code == 201, ok.text
    lead = await db_session.get(Lead, ok.json()["id"])
    assert (lead.company_name, lead.contact_name, lead.source, lead.assigned_to) == ("Hotel Mar", "Luis", LeadSource.website, None)
    assert lead.notes == "Presupuesto SEO\n\nDesde: https://magnify.ing/contacto"
    assert await _history(db_session, lead.id) == ["new"]
    assert await db_session.scalar(select(Notification.user_id).where(Notification.type == "lead_new")) == admin_user.id
    empty = await anon.post("/api/leads/inbound", json={"message": "hola"}, headers={"X-Lead-Token": "s3creto-del-formulario"})
    assert empty.status_code == 422


async def test_converting_a_lead_records_the_win(admin_client, db_session):
    created = await _lead(admin_client)
    r = await admin_client.post(f"/api/leads/{created['id']}/convert")
    assert r.status_code == 200, r.text
    assert await _history(db_session, created["id"]) == ["new", "won"]
