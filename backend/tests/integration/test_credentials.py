"""Accesos contra Postgres real: cifrado en reposo, acceso por entrada, registro."""
from __future__ import annotations

import time

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


# ── Códigos 2FA ──────────────────────────────────────────────────────

TOTP_KEY = "JBSWY3DPEHPK3PXP"


async def test_2fa_key_is_encrypted_and_only_comes_out_as_a_logged_code(admin_client, reader, db_session):
    from backend.services import totp

    created = await _create(admin_client, totp=f"otpauth://totp/WP?secret={TOTP_KEY}&issuer=WP",
                            shared_user_ids=[reader.test_user.id])
    cid = created["id"]
    assert created["has_totp"] is True and TOTP_KEY not in str(created)
    stored = await db_session.scalar(select(Credential.totp_encrypted).where(Credential.id == cid))
    assert stored.startswith("v1:") and TOTP_KEY not in stored
    assert TOTP_KEY not in (await admin_client.get("/api/credentials")).text

    r = await reader.post(f"/api/credentials/{cid}/totp")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    config = totp.TotpConfig(secret=TOTP_KEY)
    assert body["code"] in {totp.code_at(config, t) for t in (time.time() - 30, time.time(), time.time() + 30)}
    assert body["digits"] == 6 and body["period"] == 30 and 1 <= body["remaining"] <= 30
    assert TOTP_KEY not in r.text

    actions = list(await db_session.scalars(
        select(CredentialAccessLog.action).where(CredentialAccessLog.credential_id == cid).order_by(CredentialAccessLog.id)))
    assert actions == ["create", "totp"]


async def test_2fa_code_follows_access_rules_and_rate_limit(admin_client, reader):
    with_2fa = (await _create(admin_client, totp=TOTP_KEY))["id"]
    without = (await _create(admin_client, name="Sin 2FA"))["id"]
    assert (await reader.post(f"/api/credentials/{with_2fa}/totp")).status_code == 404
    assert (await admin_client.post(f"/api/credentials/{without}/totp")).status_code == 404
    credential_reveal_limiter._limiter._requests.clear()
    for _ in range(30):
        assert (await admin_client.post(f"/api/credentials/{with_2fa}/totp")).status_code == 200
    assert (await admin_client.post(f"/api/credentials/{with_2fa}/totp")).status_code == 429


async def test_2fa_key_is_set_changed_and_removed_on_edit(admin_client, db_session):
    cid = (await _create(admin_client))["id"]
    r = await admin_client.patch(f"/api/credentials/{cid}", json={"totp": "123456"})
    assert r.status_code == 422 and "código de 6 dígitos" in r.json()["detail"]
    r = await admin_client.patch(f"/api/credentials/{cid}", json={"totp": TOTP_KEY})
    assert r.status_code == 200 and r.json()["has_totp"] is True
    r = await admin_client.patch(f"/api/credentials/{cid}", json={"name": "Otro nombre"})
    assert r.json()["has_totp"] is True  # sin enviar, no cambia
    r = await admin_client.patch(f"/api/credentials/{cid}", json={"totp": ""})
    assert r.json()["has_totp"] is False
    details = list(await db_session.scalars(
        select(CredentialAccessLog.detail).where(CredentialAccessLog.action == "update").order_by(CredentialAccessLog.id)))
    assert details == ["Cambió: código 2FA", "Cambió: nombre", "Cambió: código 2FA (quitado)"]


async def test_2fa_key_in_plaintext_is_rejected_by_the_column(db_session):
    with pytest.raises(Exception, match="ck_credentials_totp_encrypted"):
        await db_session.execute(text(
            "INSERT INTO credentials (name, secret_encrypted, totp_encrypted) VALUES ('x', 'v1:x', 'JBSWY3DP')"))


# ── Importar (1Password, Bitwarden, Chrome) ──────────────────────────


async def test_import_creates_everything_for_the_importer_and_logs_the_source(writer, reader, db_session, client_row):
    items = [
        {"name": "Google Ads", "url": "https://ads.google.com", "username": "ads@magnify.ing",
         "secret": "pw-1", "totp": TOTP_KEY, "notes": "Cuenta MCC"},
        {"name": "WordPress Fit", "url": "https://fit.example/wp-admin", "username": "magnify",
         "secret": "pw-2", "client_id": client_row.id},
    ]
    r = await writer.post("/api/credentials/import", json={
        "source": "1password", "items": items, "shared_user_ids": [reader.test_user.id]})
    assert r.status_code == 201, r.text
    assert r.json() == {"created": 2} and "pw-1" not in r.text

    listed = {c["name"]: c for c in (await writer.get("/api/credentials")).json()}
    assert listed["Google Ads"]["has_totp"] is True and listed["WordPress Fit"]["client_name"] == "Fit Generation"
    assert all(c["created_by"] == writer.test_user.id for c in listed.values())
    assert [c["name"] for c in (await reader.get("/api/credentials")).json()] == ["Google Ads", "WordPress Fit"]
    assert (await reader.post(f"/api/credentials/{listed['WordPress Fit']['id']}/reveal", json={})).json() == {"secret": "pw-2"}
    details = set(await db_session.scalars(select(CredentialAccessLog.detail).where(CredentialAccessLog.action == "create")))
    assert details == {f"Importado de 1Password · Compartido con: {reader.test_user.full_name}"}


async def test_import_is_all_or_nothing_and_names_the_bad_row(admin_client, db_session):
    items = [{"name": "Bien", "secret": "pw"}, {"name": "Mal", "secret": "pw", "totp": "123456"}]
    r = await admin_client.post("/api/credentials/import", json={"source": "bitwarden", "items": items})
    assert r.status_code == 422 and r.json()["detail"].startswith("Fila 2 («Mal»):")
    assert await db_session.scalar(select(Credential.id)) is None
    r = await admin_client.post("/api/credentials/import", json={"source": "csv", "items": [{"name": "x", "secret": ""}]})
    assert r.status_code == 422 and await db_session.scalar(select(Credential.id)) is None


async def test_import_needs_write_access(reader):
    r = await reader.post("/api/credentials/import", json={"source": "csv", "items": [{"name": "x", "secret": "pw"}]})
    assert r.status_code == 403


# ── Notas cifradas ───────────────────────────────────────────────────

NOTES = "Códigos de recuperación: 1111-2222 3333-4444"


async def test_notes_are_encrypted_and_only_come_out_logged(admin_client, reader, db_session):
    created = await _create(admin_client, notes=NOTES)
    assert created["has_notes"] is True and "notes" not in created
    raw = await db_session.scalar(text("SELECT notes FROM credentials"))
    assert raw.startswith("v1:") and "1111" not in raw
    listed = (await admin_client.get("/api/credentials")).json()
    assert NOTES not in str(listed)

    assert (await reader.post(f"/api/credentials/{created['id']}/notes")).status_code == 404
    await admin_client.put(f"/api/credentials/{created['id']}/shares", json={"user_ids": [reader.test_user.id]})
    r = await reader.post(f"/api/credentials/{created['id']}/notes")
    assert r.status_code == 200 and r.json() == {"notes": NOTES}
    assert r.headers["cache-control"] == "no-store"
    actions = list(await db_session.scalars(select(CredentialAccessLog.action).where(
        CredentialAccessLog.user_id == reader.test_user.id)))
    assert actions == ["notes"]

    without = await _create(admin_client, name="Sin notas", notes="   ")
    assert without["has_notes"] is False
    assert (await admin_client.post(f"/api/credentials/{without['id']}/notes")).status_code == 404


async def test_editing_notes_logs_only_real_changes(admin_client, db_session):
    created = await _create(admin_client, notes=NOTES)
    same = await admin_client.patch(f"/api/credentials/{created['id']}", json={"notes": NOTES})
    assert same.status_code == 200
    assert await db_session.scalar(select(CredentialAccessLog.id).where(CredentialAccessLog.action == "update")) is None
    cleared = await admin_client.patch(f"/api/credentials/{created['id']}", json={"notes": ""})
    assert cleared.json()["has_notes"] is False
    assert await db_session.scalar(select(CredentialAccessLog.detail).where(
        CredentialAccessLog.action == "update")) == "Cambió: notas"


async def test_plaintext_notes_cannot_be_written_to_the_column(db_session):
    with pytest.raises(Exception, match="ck_credentials_notes_encrypted"):
        await db_session.execute(text(
            "INSERT INTO credentials (name, secret_encrypted, notes) VALUES ('x', 'v1:x', 'PIN 1234')"))


# ── Salida de alguien ────────────────────────────────────────────────


async def test_exposure_lists_what_someone_saw_and_what_to_rotate(admin_client, reader, db_session):
    seen = await _create(admin_client, name="Visto")
    rotated = await _create(admin_client, name="Visto y rotado")
    only_shared = await _create(admin_client, name="Sólo compartido")
    await _create(admin_client, name="Ajeno")
    for credential in (seen, rotated, only_shared):
        await admin_client.put(f"/api/credentials/{credential['id']}/shares", json={"user_ids": [reader.test_user.id]})
    await reader.post(f"/api/credentials/{seen['id']}/reveal", json={"purpose": "copy"})
    await reader.post(f"/api/credentials/{rotated['id']}/reveal", json={})
    time.sleep(0.01)
    await admin_client.patch(f"/api/credentials/{rotated['id']}", json={"secret": "nueva-clave"})

    assert (await reader.get(f"/api/credentials/exposure/{reader.test_user.id}")).status_code == 403
    r = await admin_client.get(f"/api/credentials/exposure/{reader.test_user.id}")
    assert r.status_code == 200, r.text
    rows = {row["name"]: row for row in r.json()}
    assert set(rows) == {"Visto", "Visto y rotado", "Sólo compartido"}
    assert rows["Visto"]["needs_rotation"] is True and rows["Visto"]["times_seen"] == 1
    assert rows["Visto y rotado"]["needs_rotation"] is False
    assert rows["Sólo compartido"]["needs_rotation"] is False and rows["Sólo compartido"]["last_seen_at"] is None
    assert all(row["shared_with_them"] for row in rows.values())

    revoked = await admin_client.post(f"/api/credentials/exposure/{reader.test_user.id}/revoke-shares")
    assert revoked.json() == {"removed": 3}
    assert (await reader.get("/api/credentials")).json() == []
    assert await db_session.scalar(select(CredentialShare.credential_id)) is None
    details = set(await db_session.scalars(select(CredentialAccessLog.detail).where(
        CredentialAccessLog.action == "share", CredentialAccessLog.detail.like("Quitado a:%"))))
    assert details == {f"Quitado a: {reader.test_user.full_name}"}
