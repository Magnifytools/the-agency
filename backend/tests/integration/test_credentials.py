"""Accesos contra Postgres real: cifrado en reposo, acceso por entrada, registro."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from backend.core.rate_limiter import credential_reveal_limiter
from backend.db.models import Client, ClientStatus, Credential, CredentialAccessLog, CredentialShare

pytestmark = pytest.mark.integration

SECRET = "Cl4ve-Sup3r-S3creta!"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_limiter():
    credential_reveal_limiter._limiter._requests.clear()
    yield
    credential_reveal_limiter._limiter._requests.clear()


@pytest_asyncio.fixture
async def client_row(db_session):
    client = Client(name="Fit Generation", status=ClientStatus.active)
    db_session.add(client)
    await db_session.commit()
    return client


@pytest_asyncio.fixture
async def reader(make_member_client):
    """Miembro con lectura de Accesos, sin escritura."""
    c = await make_member_client([("credentials", True, False)])
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def writer(make_member_client):
    c = await make_member_client([("credentials", True, True)])
    yield c
    await c.aclose()


async def _create(api, **extra) -> dict:
    body = {"name": "WordPress Fit", "url": "https://fit.example/wp-admin", "username": "magnify",
            "secret": SECRET, **extra}
    r = await api.post("/api/credentials", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_secret_is_encrypted_at_rest_and_never_listed(admin_client, db_session, client_row):
    created = await _create(admin_client, client_id=client_row.id)
    assert SECRET not in str(created) and "secret" not in created
    raw = await db_session.scalar(text("SELECT to_jsonb(c)::text FROM credentials c"))
    assert SECRET not in raw
    stored = await db_session.scalar(select(Credential.secret_encrypted))
    assert stored.startswith("v1:")

    listed = await admin_client.get("/api/credentials")
    assert listed.status_code == 200
    assert SECRET not in listed.text
    assert listed.json()[0]["client_name"] == "Fit Generation"


async def test_plaintext_cannot_be_written_to_the_column(db_session):
    with pytest.raises(Exception, match="ck_credentials_secret_encrypted"):
        await db_session.execute(text(
            "INSERT INTO credentials (name, secret_encrypted) VALUES ('x', 'texto-plano')"))


async def test_not_shared_member_gets_404_everywhere(admin_client, reader):
    created = await _create(admin_client)
    cid = created["id"]
    assert (await reader.get("/api/credentials")).json() == []
    r = await reader.post(f"/api/credentials/{cid}/reveal", json={})
    assert r.status_code == 404 and SECRET not in r.text
    assert (await reader.patch(f"/api/credentials/{cid}", json={"name": "x"})).status_code in (403, 404)
    assert (await reader.get(f"/api/credentials/{cid}/log")).status_code == 403


async def test_member_without_module_is_forbidden(member_client):
    assert (await member_client.get("/api/credentials")).status_code == 403


async def test_shared_member_reveals_and_every_reveal_is_logged(admin_client, reader, db_session):
    reader_id = reader.test_user.id
    created = await _create(admin_client, shared_user_ids=[reader_id])
    cid = created["id"]

    listed = (await reader.get("/api/credentials")).json()
    assert [c["id"] for c in listed] == [cid]
    assert listed[0]["can_manage"] is False and listed[0]["shared_with"] == []

    r = await reader.post(f"/api/credentials/{cid}/reveal", json={"purpose": "reveal"})
    assert r.status_code == 200 and r.json() == {"secret": SECRET}
    assert r.headers["cache-control"] == "no-store"
    r = await reader.post(f"/api/credentials/{cid}/reveal", json={"purpose": "copy"})
    assert r.status_code == 200

    rows = (await db_session.execute(
        select(CredentialAccessLog.action, CredentialAccessLog.user_id)
        .where(CredentialAccessLog.credential_id == cid).order_by(CredentialAccessLog.id)
    )).all()
    assert [a for a, _ in rows] == ["create", "reveal", "copy"]
    assert rows[1][1] == reader_id and rows[2][1] == reader_id

    log = (await admin_client.get(f"/api/credentials/{cid}/log")).json()
    assert [e["action"] for e in log] == ["copy", "reveal", "create"]
    assert log[0]["user_name"] == reader.test_user.full_name
    assert all(SECRET not in str(e) for e in log)

    # Un lector no puede editar ni compartir lo que no creó.
    assert (await reader.patch(f"/api/credentials/{cid}", json={"name": "x"})).status_code == 403
    assert (await reader.put(f"/api/credentials/{cid}/shares", json={"user_ids": []})).status_code == 403


async def test_reveal_is_rate_limited(admin_client):
    cid = (await _create(admin_client))["id"]
    for _ in range(30):
        assert (await admin_client.post(f"/api/credentials/{cid}/reveal", json={})).status_code == 200
    r = await admin_client.post(f"/api/credentials/{cid}/reveal", json={})
    assert r.status_code == 429 and SECRET not in r.text


async def test_creator_manages_shares_and_rotates_secret(writer, reader, db_session):
    created = await _create(writer)
    cid = created["id"]
    assert created["can_manage"] is True

    r = await writer.put(f"/api/credentials/{cid}/shares", json={"user_ids": [reader.test_user.id]})
    assert r.status_code == 200, r.text
    assert [u["id"] for u in r.json()["shared_with"]] == [reader.test_user.id]

    r = await writer.patch(f"/api/credentials/{cid}", json={"secret": "otra-clave"})
    assert r.status_code == 200 and "otra-clave" not in r.text
    assert (await reader.post(f"/api/credentials/{cid}/reveal", json={})).json() == {"secret": "otra-clave"}

    entries = (await db_session.execute(
        select(CredentialAccessLog.action, CredentialAccessLog.detail)
        .where(CredentialAccessLog.credential_id == cid).order_by(CredentialAccessLog.id)
    )).all()
    assert [a for a, _ in entries] == ["create", "share", "update", "reveal"]
    assert reader.test_user.full_name in entries[1][1]
    assert entries[2][1] == "Cambió: contraseña"

    # Quitarle el acceso: vuelve a ser un 404 para él.
    await writer.put(f"/api/credentials/{cid}/shares", json={"user_ids": []})
    assert (await reader.post(f"/api/credentials/{cid}/reveal", json={})).status_code == 404


async def test_share_only_with_users_who_can_open_the_module(admin_client, member_client):
    r = await admin_client.post("/api/credentials", json={
        "name": "GA", "secret": SECRET, "shared_user_ids": [member_client.test_user.id]})
    assert r.status_code == 422


async def test_only_admin_hard_deletes_and_the_log_keeps_the_name(admin_client, writer, db_session):
    cid = (await _create(writer))["id"]
    assert (await writer.delete(f"/api/credentials/{cid}")).status_code == 403
    assert (await admin_client.delete(f"/api/credentials/{cid}")).status_code == 204
    assert await db_session.scalar(select(Credential.id).where(Credential.id == cid)) is None
    assert await db_session.scalar(select(CredentialShare.user_id)) is None
    deleted = await db_session.scalar(select(CredentialAccessLog).where(CredentialAccessLog.action == "delete"))
    assert deleted.credential_id is None and deleted.credential_name == "WordPress Fit"


async def test_undo_journal_never_holds_the_secret(admin_client, db_session, client_row):
    before = await db_session.scalar(text("SELECT count(*) FROM change_logs"))
    cid = (await _create(admin_client, client_id=client_row.id))["id"]
    await admin_client.patch(f"/api/credentials/{cid}", json={"secret": "rotada-1234", "name": "WP"})
    await admin_client.post(f"/api/credentials/{cid}/reveal", json={})
    assert await db_session.scalar(text("SELECT count(*) FROM change_logs")) == before
    dump = await db_session.scalar(text("SELECT coalesce(string_agg(to_jsonb(c)::text, ''), '') FROM change_logs c"))
    assert SECRET not in dump and "rotada-1234" not in dump and "v1:" not in dump


async def test_client_filter_and_search(admin_client, client_row):
    await _create(admin_client, client_id=client_row.id)
    await _create(admin_client, name="Semrush", url="https://semrush.com", username="equipo")
    by_client = (await admin_client.get(f"/api/credentials?client_id={client_row.id}")).json()
    assert [c["name"] for c in by_client] == ["WordPress Fit"]
    assert [c["name"] for c in (await admin_client.get("/api/credentials?q=nada")).json()] == []
    assert [c["name"] for c in (await admin_client.get("/api/credentials?q=generation")).json()] == ["WordPress Fit"]
    assert [c["name"] for c in (await admin_client.get("/api/credentials?q=semrush")).json()] == ["Semrush"]


async def test_validation_errors_do_not_echo_the_secret(admin_client):
    r = await admin_client.post("/api/credentials", json={"name": "", "secret": SECRET})
    assert r.status_code == 422 and SECRET not in r.text
    r = await admin_client.post("/api/credentials", json={"name": "x", "secret": "a" * 2001})
    assert r.status_code == 422 and "a" * 50 not in r.text
