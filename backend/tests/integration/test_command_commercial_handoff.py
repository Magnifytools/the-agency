import pytest
from sqlalchemy import func, select

from backend.db.models import ChangeLog, Client, CommandReceipt, Project, Task
from backend.services.commands import parse_command

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("commercial", [
    "con tarifa 500", "por 500 EUR", "presupuesto 0 €", "con fee de 50,5",
])
async def test_commercial_project_command_is_a_durable_derivation_without_writes(
    admin_client, db_session, commercial,
):
    client = Client(name="Acme Commercial", status="active")
    db_session.add(client)
    await db_session.commit()
    body = {
        "request_key": "commercial-handoff-0001",
        "text": f'Crea proyecto "SEO" para cliente "Acme Commercial" {commercial}',
        "channel": "app",
    }
    response = await admin_client.post("/api/commands", json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "executed"
    assert receipt["intent"] == {"kind": "project_commercial_handoff"}
    assert receipt["result"] == {
        "kind": "derivation",
        "label": "Derivación",
        "message": "Esta orden contiene condiciones comerciales. Revísalas en el formulario de proyecto antes de crear.",
        "action": {"kind": "open_project_form", "href": "/projects?new=1"},
        "entities": [],
        "undo_available": False,
    }
    assert receipt["change_log_id"] is None
    assert await db_session.scalar(select(func.count(Project.id))) == 0
    assert await db_session.scalar(select(func.count(Task.id))) == 0
    assert await db_session.scalar(select(func.count(ChangeLog.id))) == 0
    replay = await admin_client.post("/api/commands", json=body)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    row = await db_session.scalar(select(CommandReceipt).where(CommandReceipt.id == receipt["id"]))
    assert row.raw_text == body["text"]


async def test_monthly_project_without_amount_keeps_existing_create_flow(admin_client, db_session):
    db_session.add(Client(name="Acme Monthly", status="active"))
    await db_session.commit()
    text = 'Crea proyecto "Informe mensual" para cliente "Acme Monthly"'
    assert parse_command(text)["kind"] == "create_project"
    response = await admin_client.post("/api/commands", json={
        "request_key": "commercial-handoff-0002", "text": text,
    })
    assert response.status_code == 200, response.text
    assert response.json()["result"].get("kind") != "derivation"
    assert await db_session.scalar(select(Project.id).where(Project.name == "Informe mensual"))


async def test_compound_commercial_signal_never_creates_either_entity(admin_client, db_session):
    db_session.add(Client(name="Acme Compound Price", status="active"))
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": "commercial-handoff-0003",
        "text": ('Crea proyecto "Web" para cliente "Acme Compound Price" tarifa 600 '
                 'con primera tarea "Kickoff"'),
    })
    assert response.status_code == 200
    assert response.json()["intent"]["kind"] == "project_commercial_handoff"
    assert await db_session.scalar(select(func.count(Project.id))) == 0
    assert await db_session.scalar(select(func.count(Task.id))) == 0


async def test_natural_definite_article_still_hands_commercial_project_to_review(
    admin_client, db_session,
):
    response = await admin_client.post("/api/commands", json={
        "request_key": "commercial-handoff-definite-article",
        "text": "Crea el proyecto Lanzamiento con una tarifa de 2.500 € al mes",
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["intent"] == {"kind": "project_commercial_handoff"}
    assert receipt["result"]["action"] == {
        "kind": "open_project_form", "href": "/projects?new=1",
    }
    assert receipt["result"]["entities"] == []
    assert receipt["result"]["undo_available"] is False
    assert await db_session.scalar(select(func.count(Project.id))) == 0
    assert await db_session.scalar(select(func.count(Task.id))) == 0
    assert await db_session.scalar(select(func.count(ChangeLog.id))) == 0
