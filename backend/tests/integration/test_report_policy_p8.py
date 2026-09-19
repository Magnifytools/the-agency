"""P8 report policy, ACL, cohort and external evidence regressions."""
import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestStatus,
    DigestTone,
    ExternalDeliveryAction,
    ReportCadence,
    UserPermission,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.api.routes.report_policies import put_report_policy
from backend.schemas.digest import ReportPolicyUpdate
from backend.services.digest_generation import DigestGenerationRejected, generate_locked_digest

pytestmark = pytest.mark.integration


def content():
    return {"greeting": "Hola", "date": "", "sections": {"done": [], "need": [], "next": [], "metrics": []}, "closing": "Fin"}


async def test_policy_is_opt_in_revisioned_and_disabled_keeps_responsible_access(
    admin_client, db_session, make_member_client,
):
    member = await make_member_client([("digests", True, True)])
    actor = member.test_user
    actor_id = actor.id
    client = Client(name="Cliente policy", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()

    absent = await admin_client.get(f"/api/digests/policies/{client.id}")
    assert absent.json() == {
        "client_id": client.id, "configured": False, "enabled": False, "cadence": "weekly",
        "responsible_user_id": None, "responsible_name": None, "responsible_active": None,
        "responsible_can_prepare": None, "revision": 0, "updated_at": None,
    }
    created = await admin_client.put(f"/api/digests/policies/{client.id}", json={
        "enabled": False, "cadence": "monthly", "responsible_user_id": actor_id, "revision": 0,
    })
    assert created.status_code == 200, created.text
    assert created.json()["revision"] == 1
    own = await member.get(f"/api/digests/policies/{client.id}")
    assert own.status_code == 200, (own.text, created.json(), actor_id)
    assert own.json()["enabled"] is False

    stale = await admin_client.put(f"/api/digests/policies/{client.id}", json={
        "enabled": True, "cadence": "weekly", "responsible_user_id": actor.id, "revision": 0,
    })
    assert stale.status_code == 409
    await member.aclose()


async def test_current_responsible_can_use_admin_authored_digest_and_change_revokes_assignment(
    admin_client, db_session, admin_user, make_member_client,
):
    responsible = await make_member_client([("digests", True, True)])
    other = await make_member_client([("digests", True, True)])
    client = Client(name="Cliente ACL", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    db_session.add(ClientReportPolicy(client_id=client.id, enabled=False, cadence=ReportCadence.weekly, responsible_user_id=responsible.test_user.id))
    digest = WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=DigestStatus.draft, tone=DigestTone.cercano, content=content(), created_by=admin_user.id)
    db_session.add(digest)
    await db_session.commit()

    assert (await responsible.get(f"/api/digests/{digest.id}")).status_code == 200
    assert (await responsible.get(f"/api/digests/{digest.id}/render?format=discord")).status_code == 200
    assert (await other.get(f"/api/digests/{digest.id}")).status_code == 403

    policy = await db_session.get(ClientReportPolicy, client.id)
    policy.responsible_user_id = other.test_user.id
    policy.revision += 1
    await db_session.commit()
    assert (await responsible.get(f"/api/digests/{digest.id}")).status_code == 403
    assert (await other.get(f"/api/digests/{digest.id}")).status_code == 200
    await responsible.aclose(); await other.aclose()


async def test_external_confirmation_is_versioned_idempotent_revocable_and_blocks_delete(
    admin_client, db_session, admin_user,
):
    client = Client(name="Cliente evidence", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    digest = WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=DigestStatus.reviewed, tone=DigestTone.cercano, content=content(), created_by=admin_user.id)
    db_session.add(digest); await db_session.commit()
    key = "evidence-confirm-0001"
    first = await admin_client.post(f"/api/digests/{digest.id}/external-delivery-events", headers={"X-Agency-Request-Key": key}, json={"action": "confirmed"})
    replay = await admin_client.post(f"/api/digests/{digest.id}/external-delivery-events", headers={"X-Agency-Request-Key": key}, json={"action": "confirmed"})
    conflict = await admin_client.post(f"/api/digests/{digest.id}/external-delivery-events", headers={"X-Agency-Request-Key": key}, json={"action": "revoked"})
    assert first.status_code == replay.status_code == 200
    assert first.json()["event"]["id"] == replay.json()["event"]["id"]
    assert conflict.status_code == 409
    revoked = await admin_client.post(f"/api/digests/{digest.id}/external-delivery-events", headers={"X-Agency-Request-Key": "evidence-revoke-0001"}, json={"action": "revoked"})
    assert revoked.status_code == 200
    assert revoked.json()["external_delivery"]["state"] == "unconfirmed"
    assert (await admin_client.delete(f"/api/digests/{digest.id}")).status_code == 409
    assert await db_session.scalar(select(func.count(DigestExternalDeliveryEvent.id)).where(DigestExternalDeliveryEvent.digest_id == digest.id)) == 2


async def test_preview_marks_older_confirmation_and_revocation_with_tied_timestamps(
    admin_client, db_session, admin_user, monkeypatch,
):
    period = (date(2026, 9, 7), date(2026, 9, 13))
    monkeypatch.setattr("backend.services.report_policy.policy_digest_period", lambda cadence: period)
    client = Client(name="Version evidence", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    db_session.add(ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly, responsible_user_id=admin_user.id, revision=1))
    tied = datetime(2026, 9, 19, 8, 0)
    old = WeeklyDigest(client_id=client.id, period_start=period[0], period_end=period[1], status=DigestStatus.reviewed, tone=DigestTone.cercano, content=content(), created_by=admin_user.id, created_at=tied)
    db_session.add(old); await db_session.flush()
    db_session.add(DigestExternalDeliveryEvent(digest_id=old.id, action=ExternalDeliveryAction.confirmed, actor_id=admin_user.id, request_key="old-confirmation-001", request_hash="a" * 64, created_at=tied))
    latest = WeeklyDigest(client_id=client.id, period_start=period[0], period_end=period[1], status=DigestStatus.draft, tone=DigestTone.cercano, content=content(), created_by=admin_user.id, created_at=tied)
    db_session.add(latest); await db_session.commit(); latest_id = latest.id

    preview = await admin_client.get("/api/digests/generation-preview?scope=team")
    item = next(value for value in preview.json()["items"] if value["client_id"] == client.id)
    assert item["latest_digest_id"] == latest_id
    assert item["state"] == "newer_version_unconfirmed"
    assert item["external_delivery"]["digest_id"] == old.id

    db_session.add(DigestExternalDeliveryEvent(digest_id=old.id, action=ExternalDeliveryAction.revoked, actor_id=admin_user.id, request_key="old-revocation-0001", request_hash="b" * 64))
    await db_session.commit()
    preview = await admin_client.get("/api/digests/generation-preview?scope=team")
    item = next(value for value in preview.json()["items"] if value["client_id"] == client.id)
    assert item["external_delivery"]["state"] == "unconfirmed"
    assert item["state"] == "draft"


async def test_cohort_revalidates_permission_after_provider_and_persists_nothing(
    db_session, make_member_client, monkeypatch,
):
    member = await make_member_client([("digests", True, True)])
    actor = member.test_user
    actor_id = actor.id
    client = Client(name="Cliente revoke mid AI", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    db_session.add(ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly, responsible_user_id=actor_id, revision=1))
    await db_session.commit()
    client_name = client.name

    async def collect(*args, **kwargs): return {"client_name": client_name}
    async def generate(*args, **kwargs):
        await db_session.execute(update(UserPermission).where(UserPermission.user_id == actor_id, UserPermission.module == "digests").values(can_write=False))
        return content()
    monkeypatch.setattr("backend.api.routes.report_policies.collect_digest_data", collect)
    monkeypatch.setattr("backend.api.routes.report_policies.generate_digest_content", generate)
    monkeypatch.setattr("backend.services.digest_generation.policy_digest_period", lambda cadence: (date(2026, 9, 7), date(2026, 9, 13)))

    client_id = client.id
    response = await member.post("/api/digests/generate-cohort", json={"items": [{
        "client_id": client.id, "policy_revision": 1, "period_start": "2026-09-07", "period_end": "2026-09-13",
    }], "tone": "cercano"})
    assert response.status_code == 200, response.text
    assert response.json()["results"] == [{"client_id": client_id, "outcome": "skipped", "digest_id": None, "reason": "permission_changed"}]
    assert await db_session.scalar(select(func.count(WeeklyDigest.id)).where(WeeklyDigest.client_id == client_id)) == 0
    await member.aclose()


async def test_legacy_batch_is_retired(admin_client):
    response = await admin_client.post("/api/digests/generate-batch")
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "legacy_batch_retired"


async def test_manual_generation_rejects_admin_demotion_during_provider(
    admin_client, admin_user, db_session, monkeypatch,
):
    client = Client(name="Demotion mid AI", status=ClientStatus.active)
    db_session.add_all([client, UserPermission(user_id=admin_user.id, module="digests", can_read=True, can_write=True)])
    await db_session.commit(); client_id, actor_id = client.id, admin_user.id
    async def collect(*args): return {"client_name": "Demotion mid AI"}
    async def generate(*args):
        await db_session.execute(update(User).where(User.id == actor_id).values(role=UserRole.member))
        return content()
    monkeypatch.setattr("backend.api.routes.digests.collect_digest_data", collect)
    monkeypatch.setattr("backend.api.routes.digests.generate_digest_content", generate)
    response = await admin_client.post("/api/digests/generate", json={
        "client_id": client_id, "period_start": "2026-09-07", "period_end": "2026-09-13",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "permission_changed"
    assert await db_session.scalar(select(func.count(WeeklyDigest.id)).where(WeeklyDigest.client_id == client_id)) == 0


async def test_tone_regeneration_revalidates_responsibility_after_provider(
    admin_user, db_session, make_member_client, monkeypatch,
):
    member = await make_member_client([("digests", True, True)])
    other = await make_member_client([("digests", True, True)])
    member_id, other_id = member.test_user.id, other.test_user.id
    client = Client(name="Tone ACL", status=ClientStatus.active)
    db_session.add(client); await db_session.flush()
    policy = ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly, responsible_user_id=member_id, revision=1)
    digest = WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 7), period_end=date(2026, 9, 13), status=DigestStatus.draft, tone=DigestTone.cercano, content=content(), raw_context={"client_name": client.name}, created_by=admin_user.id)
    db_session.add_all([policy, digest]); await db_session.commit(); digest_id, client_id = digest.id, client.id
    async def regenerate(*args):
        await db_session.execute(update(ClientReportPolicy).where(ClientReportPolicy.client_id == client_id).values(responsible_user_id=other_id, revision=2))
        return content()
    monkeypatch.setattr("backend.api.routes.digests.generate_digest_content", regenerate)
    response = await member.put(f"/api/digests/{digest_id}", json={"tone": "formal"})
    assert response.status_code == 403
    await db_session.rollback()
    assert await db_session.scalar(select(func.count(WeeklyDigest.id)).where(WeeklyDigest.client_id == client_id)) == 1
    await member.aclose(); await other.aclose()


async def test_policy_create_is_serialized_when_revision_zero_races(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        client = Client(name="Policy race", status=ClientStatus.active)
        setup.add(client); await setup.commit(); client_id = client.id
    actor = User(id=999999, email="detached@test", full_name="Detached", hashed_password="x", role=UserRole.admin, is_active=True)
    request = ReportPolicyUpdate(enabled=False, cadence=ReportCadence.weekly, responsible_user_id=None, revision=0)
    async with AsyncSession(engine, expire_on_commit=False) as holder, AsyncSession(engine, expire_on_commit=False) as contender:
        await holder.execute(text("SELECT pg_advisory_xact_lock(76241313, :client_id)"), {"client_id": client_id})
        waiting = asyncio.create_task(put_report_policy(client_id, request, contender, actor))
        await asyncio.sleep(0.05)
        holder.add(ClientReportPolicy(client_id=client_id, enabled=False, cadence=ReportCadence.weekly, revision=1))
        await holder.commit()
        with pytest.raises(HTTPException) as conflict:
            await waiting
        assert conflict.value.status_code == 409
        await contender.rollback()
    async with engine.begin() as conn:
        await conn.execute(delete(ClientReportPolicy).where(ClientReportPolicy.client_id == client_id))
        await conn.execute(delete(Client).where(Client.id == client_id))


async def test_individual_and_cohort_share_coverage_lock(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(email="digest-lock@test", full_name="Digest lock", hashed_password="x", role=UserRole.admin, is_active=True)
        client = Client(name="Coverage lock", status=ClientStatus.active)
        setup.add_all([actor, client]); await setup.flush()
        setup.add(ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly, responsible_user_id=actor.id, revision=1))
        await setup.commit(); actor_id, client_id = actor.id, client.id
    provider_started = asyncio.Event(); release_provider = asyncio.Event()
    async def collect(*args): return {"client_name": "Coverage lock"}
    async def slow_generate(*args):
        provider_started.set(); await release_provider.wait(); return content()
    async def fast_generate(*args): return content()
    period = (date(2026, 9, 7), date(2026, 9, 13))
    import backend.services.digest_generation as generation
    original_period = generation.policy_digest_period
    generation.policy_digest_period = lambda cadence: period
    try:
        async with AsyncSession(engine, expire_on_commit=False) as individual, AsyncSession(engine, expire_on_commit=False) as cohort:
            first = asyncio.create_task(generate_locked_digest(individual, actor_id=actor_id, client_id=client_id, period_start=period[0], period_end=period[1], tone=DigestTone.cercano, expected_revision=None, require_enabled=False, reject_existing=False, collector=collect, generator=slow_generate))
            await provider_started.wait()
            with pytest.raises(DigestGenerationRejected) as busy:
                await generate_locked_digest(cohort, actor_id=actor_id, client_id=client_id, period_start=period[0], period_end=period[1], tone=DigestTone.cercano, expected_revision=1, require_enabled=True, reject_existing=True, collector=collect, generator=fast_generate)
            assert busy.value.reason == "concurrent_generation"
            await cohort.rollback(); release_provider.set(); digest = await first; await individual.commit()
            assert digest.id is not None
    finally:
        generation.policy_digest_period = original_period
    async with engine.begin() as conn:
        await conn.execute(delete(WeeklyDigest).where(WeeklyDigest.client_id == client_id))
        await conn.execute(delete(ClientReportPolicy).where(ClientReportPolicy.client_id == client_id))
        await conn.execute(delete(Client).where(Client.id == client_id))
        await conn.execute(delete(User).where(User.id == actor_id))
