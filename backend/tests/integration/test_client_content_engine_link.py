"""Engine (= Anvil): un enlace por cliente, sin datos. Postgres real."""
from __future__ import annotations

import pytest

from backend.config import settings
from backend.db.models import Client, ClientStatus

pytestmark = pytest.mark.integration

UUID = "3f2b8c1e-9d4a-4f6b-8e2a-1c5d7e9f0a3b"


async def _client(db):
    client = Client(name="Engine link", status=ClientStatus.active)
    db.add(client)
    await db.commit()
    return client


async def test_sin_cliente_de_engine_no_hay_enlace(admin_client, db_session):
    client = await _client(db_session)
    body = (await admin_client.get(f"/api/clients/{client.id}")).json()
    assert body["content_engine_client_id"] is None and body["content_engine_url"] is None
    # Nada de lo de The Engine sale ya en la API.
    assert not [key for key in body if key.startswith("engine_")]


async def test_guardar_valida_el_uuid_y_construye_el_enlace(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENGINE_FRONTEND_URL", "https://engine.example/")
    client = await _client(db_session)
    url = f"/api/clients/{client.id}"

    resp = await admin_client.put(url, json={"content_engine_client_id": f"  {UUID.upper()} "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_engine_client_id"] == UUID
    assert resp.json()["content_engine_url"] == f"https://engine.example/?client={UUID}"
    listed = (await admin_client.get("/api/clients", params={"page_size": 1000})).json()["items"]
    assert next(i for i in listed if i["id"] == client.id)["content_engine_url"].endswith(UUID)

    for bad in ("42", "no-es-un-uuid", UUID + "x", "https://engine.magnifytools.com/?client=" + UUID):
        assert (await admin_client.put(url, json={"content_engine_client_id": bad})).status_code == 422
    assert (await admin_client.get(url)).json()["content_engine_client_id"] == UUID

    # Vacío = quitar el enlace.
    cleared = (await admin_client.put(url, json={"content_engine_client_id": ""})).json()
    assert cleared["content_engine_client_id"] is None and cleared["content_engine_url"] is None


async def test_editar_pide_escritura_en_clientes(make_member_client, admin_client, db_session):
    client = await _client(db_session)
    url = f"/api/clients/{client.id}"
    reader = await make_member_client([("clients", True, False)])
    writer = await make_member_client([("clients", True, True)])
    try:
        assert (await reader.put(url, json={"content_engine_client_id": UUID})).status_code == 403
        resp = await writer.put(url, json={"content_engine_client_id": UUID})
        assert resp.status_code == 200, resp.text
        assert (await reader.get(url)).json()["content_engine_client_id"] == UUID
    finally:
        await reader.aclose()
        await writer.aclose()


async def test_las_rutas_y_el_job_de_the_engine_ya_no_existen(admin_client):
    from backend.services.job_catalog import job_definitions

    assert (await admin_client.get("/api/engine/config")).status_code == 404
    assert (await admin_client.get("/api/engine/projects")).status_code == 404
    keys = {item.spec.key for item in job_definitions()}
    locks = {item.spec.lock_id for item in job_definitions()}
    assert "engine" not in keys and 3 not in locks  # lock 3 queda reservado
