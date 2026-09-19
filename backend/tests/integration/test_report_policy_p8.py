"""P8 report policy, ACL, cohort and external evidence regressions."""
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestStatus,
    DigestTone,
    ReportCadence,
    UserPermission,
    WeeklyDigest,
)

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
