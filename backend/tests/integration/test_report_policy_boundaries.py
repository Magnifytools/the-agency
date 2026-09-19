"""P8 deployment, concurrent evidence and preview policy boundaries on real PG."""
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from backend.api.routes.report_policies import record_external_delivery_event
from backend.db.models import (
    Client, ClientReportPolicy, ClientStatus, DigestExternalDeliveryEvent,
    DigestStatus, DigestTone, ReportCadence, User, UserRole, WeeklyDigest,
)
from backend.schemas.digest import ExternalDeliveryEventCreate
from backend.startup.report_policy_schema import ensure_report_policy_schema


async def test_report_upgrade_is_concurrent_idempotent_and_does_not_opt_in_clients(engine):
    schema = "report_upgrade_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with isolated.begin() as conn:
            for table in ("users", "clients", "weekly_digests"):
                await conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                await conn.execute(text(f"INSERT INTO {table} VALUES (1)"))
        await asyncio.gather(*(ensure_report_policy_schema(isolated) for _ in range(3)))
        async with isolated.begin() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM client_report_policies")) == 0
            await conn.execute(text("INSERT INTO client_report_policies (client_id,created_at,updated_at) VALUES (1,now(),now())"))
            row = (await conn.execute(text("SELECT enabled,cadence,responsible_user_id,revision FROM client_report_policies"))).one()
            assert row == (False, "weekly", None, 1)
            await conn.execute(text("""INSERT INTO digest_external_delivery_events
                (digest_id,action,actor_id,request_key,request_hash,created_at)
                VALUES (1,'confirmed',1,'preserved-request-key','test-hash',now())"""))
        await ensure_report_policy_schema(isolated)
        async with isolated.begin() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM digest_external_delivery_events")) == 1
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text("DELETE FROM weekly_digests WHERE id=1"))
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text("""INSERT INTO digest_external_delivery_events
                        (digest_id,action,actor_id,request_key,request_hash,created_at)
                        VALUES (1,'revoked',1,'preserved-request-key','test-hash',now())"""))
    finally:
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_one_request_key_cannot_confirm_two_versions_concurrently(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(email=f"evidence-{uuid4().hex}@test.local", full_name="Evidence actor", hashed_password="test", role=UserRole.admin, is_active=True)
        client = Client(name="Concurrent evidence", status=ClientStatus.active)
        setup.add_all([actor, client]); await setup.flush()
        digests = [WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=DigestStatus.draft, tone=DigestTone.cercano, created_by=actor.id) for _ in range(2)]
        setup.add_all(digests); await setup.commit()
        actor_id, client_id = actor.id, client.id
        digest_ids = [digest.id for digest in digests]
    async def record(digest_id):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            try:
                result = await record_external_delivery_event(digest_id, ExternalDeliveryEventCreate(action="confirmed"), "same-key-across-versions", db, actor)
                return result.event.digest_id
            except HTTPException as exc:
                await db.rollback()
                assert exc.status_code == 409
                assert exc.detail["code"] == "idempotency_conflict"
                return None
    try:
        results = await asyncio.wait_for(asyncio.gather(*(record(value) for value in digest_ids)), timeout=15)
        assert sum(value is not None for value in results) == 1
        async with AsyncSession(engine) as db:
            assert await db.scalar(select(func.count()).select_from(DigestExternalDeliveryEvent).where(DigestExternalDeliveryEvent.actor_id == actor_id)) == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(DigestExternalDeliveryEvent).where(DigestExternalDeliveryEvent.actor_id == actor_id))
            await conn.execute(delete(WeeklyDigest).where(WeeklyDigest.client_id == client_id))
            await conn.execute(delete(Client).where(Client.id == client_id))
            await conn.execute(delete(User).where(User.id == actor_id))


async def test_preview_uses_each_cadence_and_preserves_exclusion_reasons(admin_client, admin_user, db_session, monkeypatch):
    monkeypatch.setattr("backend.services.digest_periods.business_today", lambda: date(2026, 9, 19))
    definitions = [
        ("weekly", ClientStatus.active, False, "weekly", True, "eligible"),
        ("monthly", ClientStatus.active, False, "monthly", True, "eligible"),
        ("missing", ClientStatus.active, False, None, False, "policy_missing"),
        ("disabled", ClientStatus.active, False, "weekly", False, "policy_disabled"),
        ("internal", ClientStatus.active, True, "weekly", True, "internal_client"),
        ("inactive", ClientStatus.paused, False, "weekly", True, "client_inactive"),
    ]
    expected = {}
    for name, status, internal, cadence, enabled, reason in definitions:
        client = Client(name=name, status=status, is_internal=internal)
        db_session.add(client); await db_session.flush()
        if cadence:
            db_session.add(ClientReportPolicy(client_id=client.id, cadence=ReportCadence(cadence), enabled=enabled, responsible_user_id=admin_user.id))
        expected[client.id] = (cadence, reason)
    await db_session.commit()
    response = await admin_client.get("/api/digests/generation-preview?scope=team")
    assert response.status_code == 200, response.text
    for item in response.json()["items"]:
        if item["client_id"] not in expected:
            continue
        cadence, reason = expected.pop(item["client_id"])
        assert item["reason"] == reason
        assert item["eligible"] == (reason == "eligible")
        if cadence:
            assert (item["period_start"], item["period_end"]) == (("2026-08-01", "2026-08-31") if cadence == "monthly" else ("2026-09-07", "2026-09-13"))
    assert not expected


async def test_history_filters_are_validated_and_timestamp_ties_paginate(admin_client, admin_user, db_session):
    from datetime import datetime
    client = Client(name="History pagination", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    digests = [WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=DigestStatus.draft, tone=DigestTone.cercano, created_by=admin_user.id, created_at=datetime(2026, 9, 19)) for _ in range(3)]
    db_session.add_all(digests); await db_session.commit()
    first = await admin_client.get(f"/api/digests?client_id={client.id}&limit=2")
    second = await admin_client.get(f"/api/digests?client_id={client.id}&limit=2&offset=2")
    assert [row["id"] for row in first.json() + second.json()] == sorted([row.id for row in digests], reverse=True)
    assert (await admin_client.get("/api/digests?period_from=invalid")).status_code == 422
    assert (await admin_client.get("/api/digests?period_from=2026-10-01&period_to=2026-09-01")).status_code == 422


@pytest.mark.parametrize("status", [DigestStatus.draft, DigestStatus.reviewed, DigestStatus.sent])
async def test_member_deletion_without_evidence_keeps_status_rules(status, db_session, make_member_client):
    member = await make_member_client([("digests", True, True)])
    client = Client(name="Deletion boundary", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    digest = WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=status, tone=DigestTone.cercano, created_by=member.test_user.id)
    db_session.add(digest); await db_session.commit()
    digest_id = digest.id
    response = await member.delete(f"/api/digests/{digest_id}")
    assert response.status_code == (409 if status == DigestStatus.sent else 204), response.text
    remaining = await db_session.scalar(select(func.count()).select_from(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    assert remaining == (1 if status == DigestStatus.sent else 0)
    await member.aclose()
