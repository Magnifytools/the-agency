"""PostgreSQL coverage for bounded report/delivery incident collection."""
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    CommunicationOccurrence,
    CommunicationRequest,
    CommunicationSchedule,
    DailyUpdate,
    Delivery,
    Notification,
    ReportCadence,
    User,
    UserPermission,
    UserRole,
    WeeklyDigest,
)
from backend.services.deliveries import load_delivery
from backend.services.digest_periods import policy_digest_period
from backend.services.incident_report_conditions import (
    collect_report_conditions,
    report_visibility_clause,
)

NOW = datetime(2026, 9, 20, 10)


async def policy(db, actor, *, cadence=ReportCadence.weekly, enabled=True):
    client = Client(name=f"Cliente {uuid4().hex}", status=ClientStatus.active, is_internal=False)
    db.add(client)
    await db.flush()
    row = ClientReportPolicy(client_id=client.id, enabled=enabled, cadence=cadence, responsible_user_id=actor.id)
    db.add(row)
    await db.flush()
    return client, row


async def test_pending_report_requires_current_enabled_explicit_policy_and_exact_period(db_session, admin_user):
    client, row = await policy(db_session, admin_user)
    conditions = await collect_report_conditions(db_session, admin_user.id, NOW)
    assert len(conditions) == 1
    pending = next(iter(conditions.values()))
    assert pending.kind == "report_pending" and pending.entity_id == client.id
    start, end = policy_digest_period("weekly", today=NOW.date())
    assert pending.href == f"/digests?client_id={client.id}&period_start={start.isoformat()}&period_end={end.isoformat()}"
    db_session.add(WeeklyDigest(client_id=client.id, period_start=start, period_end=end, created_by=admin_user.id))
    await db_session.flush()
    assert await collect_report_conditions(db_session, admin_user.id, NOW) == {}
    row.cadence = ReportCadence.monthly
    await db_session.flush()
    assert len(await collect_report_conditions(db_session, admin_user.id, NOW)) == 1
    row.enabled = False
    await db_session.flush()
    assert await collect_report_conditions(db_session, admin_user.id, NOW) == {}


async def test_policy_owner_needs_current_digest_write_permission(db_session):
    member = User(email=f"reports-{uuid4().hex}@test.local", full_name="Report owner", hashed_password="x", role=UserRole.member, is_active=True)
    db_session.add(member)
    await db_session.flush()
    await policy(db_session, member)
    assert await collect_report_conditions(db_session, member.id, NOW) == {}
    db_session.add(UserPermission(user_id=member.id, module="digests", can_read=True, can_write=True))
    await db_session.flush()
    assert len(await collect_report_conditions(db_session, member.id, NOW)) == 1


async def test_report_current_visibility_expires_previous_period_but_preserves_authorized_history(db_session, admin_user):
    client, policy_row = await policy(db_session, admin_user)
    start, end = policy_digest_period("weekly", today=NOW.date())
    key = f"report_pending:client:{client.id}:weekly:{start.isoformat()}:{end.isoformat()}"
    notice = Notification(user_id=admin_user.id, type="report_pending", title="old", entity_type="client", entity_id=client.id, dedupe_key=key)
    db_session.add(notice); await db_session.flush()
    current = select(Notification.id).where(Notification.id == notice.id, report_visibility_clause(admin_user.id, current_only=True, now=NOW))
    assert await db_session.scalar(current) == notice.id
    policy_row.cadence = ReportCadence.monthly; await db_session.flush()
    assert await db_session.scalar(current) is None
    history = select(Notification.id).where(Notification.id == notice.id, report_visibility_clause(admin_user.id, current_only=False, now=NOW))
    assert await db_session.scalar(history) == notice.id

async def test_delivery_condition_is_actor_scoped_and_disappears_after_reviewed_resend_or_source_removal(db_session, admin_user):
    client, _ = await policy(db_session, admin_user)
    start, end = policy_digest_period("weekly", today=NOW.date())
    digest = WeeklyDigest(client_id=client.id, period_start=start, period_end=end, created_by=admin_user.id)
    db_session.add(digest)
    await db_session.flush()
    failed = Delivery(
        id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=admin_user.id, source_kind="digest", source_id=digest.id,
        source_version="v1", destination_key="team", payload={"text": "private", "steps": []}, status="failed",
        available_at=NOW, expires_at=NOW,
    )
    db_session.add(failed)
    await db_session.flush()
    conditions = await collect_report_conditions(db_session, admin_user.id, NOW)
    delivery = next(item for item in conditions.values() if item.kind == "delivery_failed")
    assert delivery.entity_type == "delivery" and delivery.entity_key == failed.id
    assert "private" not in delivery.message
    assert delivery.href == f"/deliveries/{failed.id}"

    db_session.add(Delivery(
        id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=admin_user.id, source_kind="digest", source_id=digest.id,
        source_version="v1", destination_key="team", payload={"text": "replacement", "steps": []}, status="pending",
        available_at=NOW, expires_at=NOW, resend_of=failed.id,
    ))
    await db_session.flush()
    assert not [item for item in (await collect_report_conditions(db_session, admin_user.id, NOW)).values() if item.kind == "delivery_failed"]


async def test_delivery_current_visibility_rejects_an_old_status_but_keeps_authorized_history(db_session, admin_user):
    client, _ = await policy(db_session, admin_user)
    start, end = policy_digest_period("weekly", today=NOW.date())
    digest = WeeklyDigest(client_id=client.id, period_start=start, period_end=end, created_by=admin_user.id)
    db_session.add(digest); await db_session.flush()
    delivery = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=admin_user.id, source_kind="digest", source_id=digest.id,
                        source_version="v1", destination_key="team", payload={"steps": []}, status="failed", available_at=NOW, expires_at=NOW)
    db_session.add(delivery); await db_session.flush()
    notice = Notification(user_id=admin_user.id, type="delivery_failed", title="old", dedupe_key=f"delivery_failed:delivery:{delivery.id}:failed", entity_type="delivery", entity_key=delivery.id)
    db_session.add(notice); await db_session.flush()
    statement = select(Notification.id).where(Notification.id == notice.id, report_visibility_clause(admin_user.id, current_only=True, now=NOW))
    assert await db_session.scalar(statement) == notice.id
    delivery.status = "sent"
    await db_session.flush()
    assert await db_session.scalar(statement) is None
    assert await db_session.scalar(select(Notification.id).where(Notification.id == notice.id, report_visibility_clause(admin_user.id, current_only=False, now=NOW))) == notice.id


async def test_daily_delivery_matches_real_source_authorization_after_source_removal(db_session, admin_user):
    daily = DailyUpdate(user_id=admin_user.id, date=NOW.date(), raw_text="Resumen")
    db_session.add(daily); await db_session.flush()
    delivery = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=admin_user.id, source_kind="daily", source_id=daily.id,
                        source_version="v1", destination_key="team", payload={"steps": []}, status="failed", available_at=NOW, expires_at=NOW)
    db_session.add(delivery); await db_session.flush()
    assert any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, admin_user.id, NOW)).values())
    assert (await load_delivery(db_session, delivery.id, admin_user, write=False))[0].id == delivery.id
    await db_session.delete(daily); await db_session.flush()
    assert not any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, admin_user.id, NOW)).values())
    with pytest.raises(HTTPException):
        await load_delivery(db_session, delivery.id, admin_user, write=False)


async def test_manual_delivery_tracks_current_pm_permission_like_authorize_source(db_session, monkeypatch):
    member = User(email=f"manual-{uuid4().hex}@test.local", full_name="Manual owner", hashed_password="x", role=UserRole.member, is_active=True)
    db_session.add(member); await db_session.flush()
    permission = UserPermission(user_id=member.id, module="pm", can_read=True, can_write=False)
    db_session.add(permission); await db_session.flush(); await db_session.refresh(member, ["permissions"])
    source = CommunicationRequest(request_key=uuid4().hex, owner_id=member.id, kind="pm_briefing", scope="mine", period_start=NOW.date(), period_end=NOW.date(), title="Brief", content="safe", destination_kind="team_webhook")
    db_session.add(source); await db_session.flush()
    delivery = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=member.id, source_kind="communication", source_id=source.id,
                        source_version="v1", destination_key="team", payload={"steps": []}, status="uncertain", available_at=NOW, expires_at=NOW)
    db_session.add(delivery); await db_session.flush()
    monkeypatch.setattr("backend.services.incident_report_conditions.is_enabled", lambda module: module != "communications")
    assert any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    assert (await load_delivery(db_session, delivery.id, member, write=False))[0].id == delivery.id
    source.destination_kind = "owner_dm"
    await db_session.flush()
    assert not any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    with pytest.raises(HTTPException):
        await load_delivery(db_session, delivery.id, member, write=False)
    permission.can_read = False; await db_session.flush(); await db_session.refresh(member, ["permissions"])
    assert not any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    with pytest.raises(HTTPException):
        await load_delivery(db_session, delivery.id, member, write=False)


async def test_scheduled_delivery_keeps_disabled_schedule_readable_but_hides_deleted_occurrence(db_session):
    member = User(email=f"scheduled-{uuid4().hex}@test.local", full_name="Schedule owner", hashed_password="x", role=UserRole.member, is_active=True)
    db_session.add(member); await db_session.flush()
    db_session.add(UserPermission(user_id=member.id, module="tasks", can_read=True, can_write=False)); await db_session.flush()
    await db_session.refresh(member, ["permissions"])
    schedule = CommunicationSchedule(policy_key=f"user:{member.id}:morning", kind="morning", approved_by=member.id, recipient_id=member.id,
                                     enabled=False, channels=["in_app"], time="08:00", minutes_before=None, quiet_start=None, quiet_end=None, revision=1, effective_from=NOW)
    db_session.add(schedule); await db_session.flush()
    occurrence = CommunicationOccurrence(occurrence_key=uuid4().hex, schedule_id=schedule.id, recipient_id=member.id, kind="morning", channel="in_app",
                                         period_start=NOW.date(), period_end=NOW.date(), due_at=NOW, expires_at=NOW, state="planned")
    db_session.add(occurrence); await db_session.flush()
    source = CommunicationRequest(request_key=uuid4().hex, owner_id=member.id, kind="scheduled_morning", scope="mine", period_start=NOW.date(), period_end=NOW.date(), title="Plan", content="safe", destination_kind="in_app")
    db_session.add(source); await db_session.flush(); occurrence.request_id = source.id; await db_session.flush()
    delivery = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=member.id, source_kind="communication", source_id=source.id,
                        source_version="v1", destination_key="in_app", payload={"steps": []}, status="failed", available_at=NOW, expires_at=NOW)
    db_session.add(delivery); await db_session.flush()
    assert any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    assert (await load_delivery(db_session, delivery.id, member, write=False))[0].id == delivery.id
    occurrence.kind = "meeting"
    source.kind = "scheduled_meeting"
    await db_session.execute(delete(UserPermission).where(UserPermission.user_id == member.id, UserPermission.module == "tasks"))
    await db_session.flush()
    assert any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    assert (await load_delivery(db_session, delivery.id, member, write=False))[0].id == delivery.id
    occurrence.kind = "unknown"
    source.kind = "scheduled_unknown"
    await db_session.flush()
    assert not any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    with pytest.raises(HTTPException):
        await load_delivery(db_session, delivery.id, member, write=False)
    occurrence.kind = "meeting"
    source.kind = "scheduled_meeting"
    await db_session.flush()
    await db_session.delete(occurrence); await db_session.flush()
    assert not any(item.entity_key == delivery.id for item in (await collect_report_conditions(db_session, member.id, NOW)).values())
    with pytest.raises(HTTPException):
        await load_delivery(db_session, delivery.id, member, write=False)
