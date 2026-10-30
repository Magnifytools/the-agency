"""Peticiones fuera de alcance contra Postgres real: alta, decisión, totales,
permisos, Por aclarar y Deshacer."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.db.models import (
    ChangeLog, Client, ClientScopeRequest, ClientStatus, InboxNote, InboxNoteStatus, Project,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def setup(db_session):
    client = Client(name="Sage", status=ClientStatus.active)
    other = Client(name="Otro", status=ClientStatus.active)
    db_session.add_all([client, other])
    await db_session.flush()
    project = Project(name="SEO mensual", client_id=client.id, is_recurring=True)
    foreign = Project(name="Ajeno", client_id=other.id)
    db_session.add_all([project, foreign])
    await db_session.commit()
    return client, project, foreign


async def test_apuntar_decidir_y_totales_del_mes(admin_client, setup):
    client, project, _ = setup
    base = f"/api/clients/{client.id}/scope-requests"
    created = await admin_client.post(base, json={
        "title": "  Landing de Black Friday  ", "detail": "Pedida por Slack", "estimated_minutes": 90,
        "project_id": project.id, "requested_on": "2026-10-05",
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Landing de Black Friday"
    assert body["decision"] == "pending" and body["decided_at"] is None
    assert body["project_name"] == "SEO mensual"
    assert body["created_by_name"] == "Admin Integration"

    await admin_client.post(base, json={"title": "Cambio de menú", "estimated_minutes": 30,
                                        "requested_on": "2026-10-20", "decision": "absorb"})
    await admin_client.post(base, json={"title": "Antigua sin decidir", "estimated_minutes": 15,
                                        "requested_on": "2026-09-28"})
    await admin_client.post(base, json={"title": "Antigua decidida", "estimated_minutes": 15,
                                        "requested_on": "2026-09-27", "decision": "bill"})

    decided = await admin_client.patch(f"{base}/{body['id']}", json={"decision": "bill", "decision_note": "Presupuesto aparte"})
    assert decided.status_code == 200
    assert decided.json()["decision"] == "bill"
    assert decided.json()["decided_by_name"] == "Admin Integration"
    assert decided.json()["decided_at"] is not None

    listing = (await admin_client.get(f"{base}?month=2026-10")).json()
    assert listing["totals"] == {"absorbed_minutes": 30, "billable_minutes": 90, "swapped_minutes": 0,
                                 "pending_minutes": 0, "count": 2}
    # Lo pendiente de septiembre se ve (pide decisión); lo decidido de septiembre no.
    assert [i["title"] for i in listing["items"]] == ["Cambio de menú", "Landing de Black Friday", "Antigua sin decidir"]

    back = await admin_client.patch(f"{base}/{body['id']}", json={"decision": "pending"})
    assert back.json()["decided_at"] is None and back.json()["decided_by_name"] is None
    assert (await admin_client.get(f"{base}?month=2026-13")).status_code == 422


async def test_proyecto_de_otro_cliente_y_cliente_inexistente(admin_client, setup):
    client, _, foreign = setup
    resp = await admin_client.post(f"/api/clients/{client.id}/scope-requests", json={
        "title": "X", "estimated_minutes": 10, "project_id": foreign.id,
    })
    assert resp.status_code == 422
    assert (await admin_client.post("/api/clients/999999/scope-requests", json={
        "title": "X", "estimated_minutes": 10,
    })).status_code == 404
    assert (await admin_client.get("/api/clients/999999/scope-requests")).status_code == 404


async def test_permisos_por_modulo(make_member_client, admin_client, setup):
    client, project, _ = setup
    base = f"/api/clients/{client.id}/scope-requests"
    created = (await admin_client.post(base, json={"title": "Con proyecto", "estimated_minutes": 20,
                                                   "project_id": project.id})).json()

    nobody = await make_member_client([])
    assert (await nobody.get(base)).status_code == 403

    reader = await make_member_client([("clients", True, False)])
    items = (await reader.get(base)).json()["items"]
    # Sin lectura de proyectos no se ve a qué proyecto va.
    assert items[0]["project_id"] is None and items[0]["project_name"] is None
    assert (await reader.post(base, json={"title": "X", "estimated_minutes": 5})).status_code == 403

    writer = await make_member_client([("clients", True, True)])
    assert (await writer.post(base, json={"title": "Sin proyecto", "estimated_minutes": 5})).status_code == 201
    assert (await writer.post(base, json={"title": "X", "estimated_minutes": 5,
                                          "project_id": project.id})).status_code == 403
    assert (await writer.patch(f"{base}/{created['id']}", json={"decision": "swap"})).status_code == 200
    # Otro cliente en la URL: el mismo 404.
    assert (await writer.patch(f"/api/clients/{client.id + 99999}/scope-requests/{created['id']}",
                               json={"decision": "bill"})).status_code == 404


async def test_desde_por_aclarar(admin_client, admin_user, setup, db_session):
    client, project, _ = setup
    note = InboxNote(user_id=admin_user.id, raw_text="Quieren un informe extra de Navidad\nLo pidió Marta por llamada",
                     status=InboxNoteStatus.pending)
    db_session.add(note)
    await db_session.commit()

    resp = await admin_client.post(f"/api/inbox/{note.id}/scope-request", json={
        "client_id": client.id, "estimated_minutes": 120, "project_id": project.id,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processed"
    assert resp.json()["resolved_as"] == "scope_request"
    row = await db_session.get(ClientScopeRequest, resp.json()["resolved_entity_id"])
    assert row.title == "Quieren un informe extra de Navidad"
    assert row.detail.startswith("Quieren un informe extra de Navidad\nLo pidió Marta")
    assert row.requested_on <= date.today()

    # Reintento: misma respuesta, sin duplicar.
    again = await admin_client.post(f"/api/inbox/{note.id}/scope-request", json={
        "client_id": client.id, "estimated_minutes": 120,
    })
    assert again.status_code == 200
    assert len((await db_session.scalars(select(ClientScopeRequest.id))).all()) == 1
    # Ya no se puede convertir en tarea.
    assert (await admin_client.post(f"/api/inbox/{note.id}/convert-to-task", json={})).status_code == 409


async def test_borrar_se_deshace(admin_client, setup, db_session):
    client, _, _ = setup
    base = f"/api/clients/{client.id}/scope-requests"
    created = (await admin_client.post(base, json={"title": "Se borra por error", "estimated_minutes": 45,
                                                   "decision": "absorb"})).json()
    assert (await admin_client.delete(f"{base}/{created['id']}")).status_code == 204
    change = await db_session.scalar(select(ChangeLog).order_by(ChangeLog.id.desc()))
    assert {op["entity_type"] for op in change.operations} == {"client_scope_request"}

    undone = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    restored = await db_session.get(ClientScopeRequest, created["id"])
    assert restored is not None and restored.decision == "absorb" and restored.decided_at is not None
