from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.db.models import (
    ChangeLog,
    Client,
    ClientContact,
    ClientOnboardingReceipt,
    Project,
    User,
    UserPermission,
    UserRole,
)
from backend.schemas.client_onboarding import ClientOnboardingCreate
from backend.services import change_journal
from backend.services.client_onboarding import (
    ONBOARDING_LOCK_NAMESPACE,
    _lock_id,
    create_onboarding,
    recover_onboarding,
)


pytestmark = pytest.mark.integration


def _key(prefix: str = "onboarding") -> str:
    return f"{prefix}_{uuid4().hex}"


def _payload(name: str = "Cliente compuesto", *, project: bool = True) -> dict:
    body: dict = {
        "client": {"name": name, "website": "https://example.test"},
        "contacts": [
            {"name": "Ada Cliente", "email": "ada@example.test", "is_primary": True},
            {"name": "Lin Cliente", "is_primary": False},
        ],
    }
    if project:
        body["project"] = {
            "name": f"Proyecto {name}",
            "gsc_url": "sc-domain:example.test",
            "ga4_property_id": "123456",
        }
    return body


async def _wait_for_advisory_waiter(engine, user_id: int, request_key: str) -> None:
    lock_id = _lock_id(user_id, request_key) & 0xFFFFFFFF
    for _ in range(100):
        async with engine.connect() as conn:
            waiting = await conn.scalar(text("""
                SELECT count(*) FROM pg_locks
                WHERE locktype='advisory' AND classid=:namespace AND objid=:lock_id
                  AND objsubid=2 AND NOT granted
            """), {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": lock_id})
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the onboarding request did not wait on its advisory lock")


async def test_full_bundle_is_atomic_and_replays_same_ids(admin_client, db_session):
    key = _key()
    body = _payload()

    created = await admin_client.post(
        "/api/clients/onboarding", json=body,
        headers={"X-Agency-Request-Key": key},
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["status"] == "confirmed"
    assert result["replayed"] is False
    assert result["undo_state"] == "available"
    assert len(result["contact_ids"]) == 2
    assert result["project_id"] is not None

    project = await db_session.get(Project, result["project_id"])
    assert project.client_id == result["client_id"]
    assert project.start_date is None
    assert project.target_end_date is None
    assert project.gsc_url == "sc-domain:example.test"
    assert project.ga4_property_id == "123456"
    receipt = await db_session.get(
        ClientOnboardingReceipt,
        {"user_id": admin_client.test_user.id, "request_key": key},
    )
    assert receipt.result == {
        "client_id": result["client_id"],
        "contact_ids": result["contact_ids"],
        "project_id": result["project_id"],
    }

    replay = await admin_client.post(
        "/api/clients/onboarding",
        json={**body, "contacts": body["contacts"], "project": body["project"]},
        headers={"X-Agency-Request-Key": key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == {**result, "replayed": True}
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == body["client"]["name"])
    ) == 1


async def test_same_key_with_different_intent_conflicts_without_partial_writes(
    admin_client, db_session,
):
    key = _key()
    first = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Primero", project=False),
        headers={"X-Agency-Request-Key": key},
    )
    assert first.status_code == 201

    conflict = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Segundo", project=False),
        headers={"X-Agency-Request-Key": key},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Segundo")
    ) == 0


async def test_recovery_before_delayed_post_installs_cancellation_barrier(
    admin_client, db_session,
):
    key = _key("delayed")
    recovered = await admin_client.post(f"/api/clients/onboarding-attempts/{key}/recover")
    assert recovered.status_code == 200
    assert recovered.json() == {
        "status": "not_committed", "client_id": None, "contact_ids": [],
        "project_id": None, "replayed": False, "undo_state": "unavailable",
        "change_log_id": None,
    }

    delayed = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Nunca creado", project=False),
        headers={"X-Agency-Request-Key": key},
    )
    assert delayed.status_code == 409
    assert delayed.json()["detail"]["code"] == "attempt_cancelled"
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Nunca creado")
    ) == 0


async def test_project_requires_current_write_permission_and_rolls_back(
    make_member_client, db_session,
):
    member = await make_member_client([("clients", True, True)])
    try:
        allowed = await member.post(
            "/api/clients/onboarding", json=_payload("Sólo cliente", project=False),
            headers={"X-Agency-Request-Key": _key()},
        )
        assert allowed.status_code == 201, allowed.text

        denied = await member.post(
            "/api/clients/onboarding", json=_payload("Sin proyectos"),
            headers={"X-Agency-Request-Key": _key()},
        )
        assert denied.status_code == 403
        assert await db_session.scalar(
            select(func.count(Client.id)).where(Client.name == "Sin proyectos")
        ) == 0
    finally:
        await member.aclose()


async def test_hidden_nested_project_module_blocks_admin_and_writes(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "projects")
    response = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Proyecto oculto"),
        headers={"X-Agency-Request-Key": _key()},
    )
    assert response.status_code == 404
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Proyecto oculto")
    ) == 0


async def test_hidden_clients_module_blocks_the_compound_service(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "clients")
    response = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Clientes ocultos", project=False),
        headers={"X-Agency-Request-Key": _key()},
    )
    assert response.status_code == 404
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Clientes ocultos")
    ) == 0


async def test_confirmed_project_result_is_not_exposed_after_permission_revocation(
    make_member_client, db_session,
):
    member = await make_member_client([
        ("clients", True, True), ("projects", True, True),
    ])
    key = _key("fresh-acl")
    try:
        created = await member.post(
            "/api/clients/onboarding", json=_payload("Permiso revocado"),
            headers={"X-Agency-Request-Key": key},
        )
        assert created.status_code == 201, created.text
        permission = await db_session.scalar(select(UserPermission).where(
            UserPermission.user_id == member.test_user.id,
            UserPermission.module == "projects",
        ))
        permission.can_write = False
        await db_session.commit()
        db_session.expire(member.test_user, ["permissions"])

        recovered = await member.post(f"/api/clients/onboarding-attempts/{key}/recover")
        assert recovered.status_code == 403
        assert "project_id" not in recovered.json()
    finally:
        await member.aclose()


async def test_validation_limits_contacts_and_primary_before_any_write(
    admin_client, db_session,
):
    too_many = _payload("Demasiados", project=False)
    too_many["contacts"] = [{"name": f"Contacto {i}"} for i in range(51)]
    response = await admin_client.post(
        "/api/clients/onboarding", json=too_many,
        headers={"X-Agency-Request-Key": _key()},
    )
    assert response.status_code == 422

    two_primary = _payload("Dos principales", project=False)
    two_primary["contacts"] = [
        {"name": "Uno", "is_primary": True},
        {"name": "Dos", "is_primary": True},
    ]
    response = await admin_client.post(
        "/api/clients/onboarding", json=two_primary,
        headers={"X-Agency-Request-Key": _key()},
    )
    assert response.status_code == 422
    assert await db_session.scalar(select(func.count(Client.id)).where(
        Client.name.in_(["Demasiados", "Dos principales"])
    )) == 0


async def test_maximum_bundle_produces_one_undo_with_52_operations(
    admin_client, db_session,
):
    body = _payload("Máximo permitido")
    body["contacts"] = [{"name": f"Contacto {i}"} for i in range(50)]
    response = await admin_client.post(
        "/api/clients/onboarding", json=body,
        headers={"X-Agency-Request-Key": _key("maximum")},
    )
    assert response.status_code == 201, response.text
    journal = await db_session.get(ChangeLog, response.json()["change_log_id"])
    assert len(journal.operations) == 52
    assert [operation["entity_type"] for operation in journal.operations].count(
        "client_contact"
    ) == 50


async def test_invalid_second_operation_rolls_back_client_and_contacts(
    admin_client, db_session,
):
    key = _key("bad-owner")
    journals_before = await db_session.scalar(select(func.count(ChangeLog.id)))
    body = _payload("Rollback total")
    body["project"]["owner_id"] = 999_999
    response = await admin_client.post(
        "/api/clients/onboarding", json=body,
        headers={"X-Agency-Request-Key": key},
    )
    assert response.status_code == 422
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Rollback total")
    ) == 0
    assert await db_session.scalar(
        select(func.count(ClientContact.id)).where(ClientContact.email == "ada@example.test")
    ) == 0
    assert await db_session.get(
        ClientOnboardingReceipt,
        {"user_id": admin_client.test_user.id, "request_key": key},
    ) is None
    assert await db_session.scalar(select(func.count(ChangeLog.id))) == journals_before


async def test_missing_grouped_journal_aborts_every_write(
    admin_client, db_session, monkeypatch,
):
    import backend.services.client_onboarding as service

    key = _key("missing-journal")
    journals_before = await db_session.scalar(select(func.count(ChangeLog.id)))
    monkeypatch.setattr(service, "prepare_entry", lambda _session: None)
    response = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Sin historial"),
        headers={"X-Agency-Request-Key": key},
    )
    assert response.status_code == 500
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Sin historial")
    ) == 0
    assert await db_session.scalar(
        select(func.count(ClientContact.id)).where(ClientContact.email == "ada@example.test")
    ) == 0
    assert await db_session.get(
        ClientOnboardingReceipt,
        {"user_id": admin_client.test_user.id, "request_key": key},
    ) is None
    assert await db_session.scalar(select(func.count(ChangeLog.id))) == journals_before


async def test_contact_writer_failure_rolls_back_receipt_and_partial_bundle(
    admin_client, db_session, monkeypatch,
):
    import backend.services.client_onboarding as service

    key = _key("contact-failure")
    journals_before = await db_session.scalar(select(func.count(ChangeLog.id)))
    real_create_contact = service.create_contact
    calls = 0

    async def fail_second_contact(db, client_id, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("controlled contact failure")
        return await real_create_contact(db, client_id, data)

    monkeypatch.setattr(service, "create_contact", fail_second_contact)
    response = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Contacto falla", project=False),
        headers={"X-Agency-Request-Key": key},
    )
    assert response.status_code == 500
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Contacto falla")
    ) == 0
    assert await db_session.scalar(
        select(func.count(ClientContact.id)).where(ClientContact.name.in_([
            "Ada Cliente", "Lin Cliente",
        ]))
    ) == 0
    assert await db_session.get(
        ClientOnboardingReceipt,
        {"user_id": admin_client.test_user.id, "request_key": key},
    ) is None
    assert await db_session.scalar(select(func.count(ChangeLog.id))) == journals_before


async def test_recovery_reports_undo_state_without_guessing(admin_client, db_session):
    key = _key("undo")
    created = await admin_client.post(
        "/api/clients/onboarding", json=_payload("Undo projection", project=False),
        headers={"X-Agency-Request-Key": key},
    )
    result = created.json()
    assert result["undo_state"] == "available"
    journal = await db_session.get(ChangeLog, result["change_log_id"])
    journal.undone_at = journal.created_at
    await db_session.commit()

    recovered = await admin_client.post(f"/api/clients/onboarding-attempts/{key}/recover")
    assert recovered.status_code == 200
    assert recovered.json()["undo_state"] == "undone"

    receipt = await db_session.get(
        ClientOnboardingReceipt,
        {"user_id": admin_client.test_user.id, "request_key": key},
    )
    receipt.change_log_id = None
    await db_session.commit()
    unavailable = await admin_client.post(f"/api/clients/onboarding-attempts/{key}/recover")
    assert unavailable.json()["undo_state"] == "unavailable"
    assert unavailable.json()["change_log_id"] is None


async def test_real_undo_then_replay_reports_original_undone_result_without_recreating(
    admin_client, db_session,
):
    key = _key("real-undo")
    body = _payload("Alta deshecha")
    created = await admin_client.post(
        "/api/clients/onboarding", json=body,
        headers={"X-Agency-Request-Key": key},
    )
    assert created.status_code == 201, created.text
    original = created.json()

    undone = await admin_client.post(f"/api/changes/{original['change_log_id']}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    assert await db_session.get(Client, original["client_id"]) is None
    assert await db_session.get(Project, original["project_id"]) is None
    for contact_id in original["contact_ids"]:
        assert await db_session.get(ClientContact, contact_id) is None

    replay = await admin_client.post(
        "/api/clients/onboarding", json=body,
        headers={"X-Agency-Request-Key": key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == {
        **original,
        "replayed": True,
        "undo_state": "undone",
    }
    assert await db_session.scalar(
        select(func.count(Client.id)).where(Client.name == "Alta deshecha")
    ) == 0


async def test_same_request_key_is_isolated_per_user(make_member_client):
    first = await make_member_client([("clients", True, True)])
    second = await make_member_client([("clients", True, True)])
    key = _key("shared")
    try:
        first_response = await first.post(
            "/api/clients/onboarding", json=_payload("Clave usuario uno", project=False),
            headers={"X-Agency-Request-Key": key},
        )
        second_response = await second.post(
            "/api/clients/onboarding", json=_payload("Clave usuario dos", project=False),
            headers={"X-Agency-Request-Key": key},
        )
        assert first_response.status_code == 201, first_response.text
        assert second_response.status_code == 201, second_response.text
        assert first_response.json()["client_id"] != second_response.json()["client_id"]
    finally:
        await first.aclose()
        await second.aclose()


async def test_two_real_sessions_with_same_key_create_one_bundle(engine):
    suffix = uuid4().hex[:10]
    key = _key("race")
    email = f"onboarding-race-{suffix}@test.local"
    name = f"Race client {suffix}"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email=email, full_name="Onboarding Racer", hashed_password="unused",
            role=UserRole.admin, is_active=True,
        )
        setup.add(actor)
        await setup.commit()
        actor_id = actor.id

    payload = ClientOnboardingCreate.model_validate(_payload(name))

    async def create_once():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            actor = await session.get(User, actor_id)
            change_journal.set_actor(actor_id)
            try:
                response, created = await create_onboarding(session, actor, key, payload)
                return response, created
            finally:
                change_journal.set_actor(None)

    first, second = await asyncio.gather(create_once(), create_once())
    assert sorted([first[1], second[1]]) == [False, True]
    assert first[0].client_id == second[0].client_id
    assert first[0].contact_ids == second[0].contact_ids
    assert first[0].project_id == second[0].project_id
    async with AsyncSession(engine) as verify:
        assert await verify.scalar(
            select(func.count(Client.id)).where(Client.name == name)
        ) == 1


async def test_recover_reports_processing_while_original_attempt_holds_lock(engine):
    suffix = uuid4().hex[:10]
    key = _key("processing")
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email=f"processing-{suffix}@test.local", full_name="Processing Actor",
            hashed_password="unused", role=UserRole.admin, is_active=True,
        )
        setup.add(actor)
        await setup.commit()
        actor_id = actor.id

    holder = AsyncSession(engine, expire_on_commit=False)
    contender = AsyncSession(engine, expire_on_commit=False)
    try:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": _lock_id(actor_id, key)},
        )
        actor = await contender.get(User, actor_id)
        response, status_code = await recover_onboarding(contender, actor, key)
        assert status_code == 202
        assert response.status == "processing"
        assert await contender.get(
            ClientOnboardingReceipt, {"user_id": actor_id, "request_key": key},
        ) is None
    finally:
        await holder.rollback()
        await holder.close()
        await contender.close()


@pytest.mark.parametrize("revocation", ["permission", "inactive"])
async def test_create_revalidates_actor_after_waiting_for_advisory_lock(
    engine, revocation,
):
    suffix = uuid4().hex[:10]
    key = _key("fresh-create")
    name = f"Fresh actor {suffix}"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email=f"fresh-create-{suffix}@test.local", full_name="Fresh create",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        setup.add(actor)
        await setup.flush()
        setup.add(UserPermission(
            user_id=actor.id, module="clients", can_read=True, can_write=True,
        ))
        await setup.commit()
        actor_id = actor.id

    holder = AsyncSession(engine, expire_on_commit=False)
    try:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": _lock_id(actor_id, key)},
        )

        async def delayed_create():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                stale_actor = await session.get(User, actor_id)
                change_journal.set_actor(actor_id)
                try:
                    await create_onboarding(
                        session, stale_actor, key,
                        ClientOnboardingCreate.model_validate(_payload(name, project=False)),
                    )
                except HTTPException as exc:
                    await session.rollback()
                    return exc
                finally:
                    change_journal.set_actor(None)
            raise AssertionError("revoked actor unexpectedly created onboarding")

        attempt = asyncio.create_task(delayed_create())
        await _wait_for_advisory_waiter(engine, actor_id, key)
        async with AsyncSession(engine, expire_on_commit=False) as admin:
            locked_actor = (await admin.execute(
                select(User).options(noload("*")).where(User.id == actor_id)
                .with_for_update(key_share=True).execution_options(populate_existing=True)
            )).scalar_one()
            if revocation == "inactive":
                locked_actor.is_active = False
            else:
                await admin.execute(delete(UserPermission).where(
                    UserPermission.user_id == actor_id,
                    UserPermission.module == "clients",
                ))
            await admin.commit()
        await holder.rollback()
        denied = await asyncio.wait_for(attempt, timeout=2)
        assert denied.status_code == 403
    finally:
        if holder.in_transaction():
            await holder.rollback()
        await holder.close()

    async with AsyncSession(engine) as verify:
        assert await verify.scalar(select(func.count(Client.id)).where(Client.name == name)) == 0
        assert await verify.get(
            ClientOnboardingReceipt, {"user_id": actor_id, "request_key": key},
        ) is None


async def test_recover_revalidates_project_permission_after_waiting_for_lock(engine):
    suffix = uuid4().hex[:10]
    key = _key("fresh-recover")
    name = f"Fresh recover {suffix}"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email=f"fresh-recover-{suffix}@test.local", full_name="Fresh recover",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        setup.add(actor)
        await setup.flush()
        setup.add_all([
            UserPermission(user_id=actor.id, module="clients", can_read=True, can_write=True),
            UserPermission(user_id=actor.id, module="projects", can_read=True, can_write=True),
        ])
        await setup.commit()
        actor_id = actor.id

    async with AsyncSession(engine, expire_on_commit=False) as create_db:
        actor = await create_db.get(User, actor_id)
        change_journal.set_actor(actor_id)
        try:
            created, _ = await create_onboarding(
                create_db, actor, key,
                ClientOnboardingCreate.model_validate(_payload(name)),
            )
        finally:
            change_journal.set_actor(None)
        client_id = created.client_id

    holder = AsyncSession(engine, expire_on_commit=False)
    try:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": _lock_id(actor_id, key)},
        )

        async with AsyncSession(engine, expire_on_commit=False) as busy_recover:
            response, status_code = await recover_onboarding(
                busy_recover, SimpleNamespace(id=actor_id), key,
            )
            assert status_code == 202 and response.status == "processing"
        async with AsyncSession(engine, expire_on_commit=False) as admin:
            await admin.execute(
                select(User).options(noload("*")).where(User.id == actor_id)
                .with_for_update(key_share=True).execution_options(populate_existing=True)
            )
            await admin.execute(delete(UserPermission).where(
                UserPermission.user_id == actor_id,
                UserPermission.module == "projects",
            ))
            await admin.commit()
        await holder.rollback()
        async with AsyncSession(engine, expire_on_commit=False) as retry:
            with pytest.raises(HTTPException) as denied:
                await recover_onboarding(retry, SimpleNamespace(id=actor_id), key)
            assert denied.value.status_code == 403
            await retry.rollback()
    finally:
        if holder.in_transaction():
            await holder.rollback()
        await holder.close()

    async with AsyncSession(engine) as verify:
        assert await verify.get(Client, client_id) is not None
        receipt = await verify.get(
            ClientOnboardingReceipt, {"user_id": actor_id, "request_key": key},
        )
        assert receipt is not None and receipt.status == "confirmed"
