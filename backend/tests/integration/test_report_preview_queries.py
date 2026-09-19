"""Cohort projections stay bounded as clients and version histories grow."""
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import event

from backend.db.models import (
    Client, ClientReportPolicy, ClientStatus, Delivery, DigestExternalDeliveryEvent,
    DigestStatus, DigestTone, ExternalDeliveryAction, ReportCadence, User,
    UserPermission, UserRole, WeeklyDigest,
)
from backend.services.report_policy import preview_items


async def test_cohort_batches_queries_and_keeps_latest_receipts_per_exact_coverage(
    db_session, engine, admin_user, monkeypatch,
):
    period = (date(2026, 9, 7), date(2026, 9, 13))
    monkeypatch.setattr("backend.services.report_policy.policy_digest_period", lambda cadence: period)
    responsible = User(email=f"cohort-{uuid4().hex}@test.local", full_name="Report owner", hashed_password="test", role=UserRole.member, is_active=True)
    db_session.add(responsible); await db_session.flush()
    db_session.add(UserPermission(user_id=responsible.id, module="digests", can_read=True, can_write=True))
    rows, expected = [], {}
    stamp = datetime(2026, 9, 19, 8)
    for index in range(30):
        client = Client(name=f"Cohort {index}", status=ClientStatus.active)
        db_session.add(client); await db_session.flush()
        policy = ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly, responsible_user_id=responsible.id)
        db_session.add(policy)
        versions = [WeeklyDigest(client_id=client.id, period_start=period[0], period_end=period[1], status=DigestStatus.draft, tone=DigestTone.cercano, created_by=admin_user.id, created_at=stamp, content={"greeting": "Large content must not be loaded"}) for _ in range(4)]
        unrelated = WeeklyDigest(client_id=client.id, period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), status=DigestStatus.sent, tone=DigestTone.cercano, created_by=admin_user.id, created_at=stamp + timedelta(days=1))
        db_session.add_all(versions + [unrelated]); await db_session.flush()
        for version, action in [(versions[0], ExternalDeliveryAction.confirmed), (versions[-1], ExternalDeliveryAction.confirmed), (versions[-1], ExternalDeliveryAction.revoked), (unrelated, ExternalDeliveryAction.confirmed)]:
            db_session.add(DigestExternalDeliveryEvent(digest_id=version.id, action=action, actor_id=admin_user.id, request_key=uuid4().hex, request_hash="a" * 64, created_at=stamp))
        last_delivery_id = None
        for offset, status in enumerate(["sent", "failed"]):
            last_delivery_id = str(uuid4())
            db_session.add(Delivery(id=last_delivery_id, dedupe_key=uuid4().hex, actor_id=admin_user.id, source_kind="digest", source_id=versions[-1].id, source_version="test", destination_key="synthetic", payload={}, status=status, available_at=stamp, expires_at=stamp + timedelta(days=1), created_at=stamp + timedelta(seconds=offset)))
        rows.append((client, policy))
        expected[client.id] = (versions[-1].id, versions[0].id, last_delivery_id)
    await db_session.flush()

    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        single = await preview_items(db_session, rows[:1])
        single_count = len(statements)
        statements.clear()
        items = await preview_items(db_session, rows)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert len(single) == 1
    assert len(items) == 30
    assert len(statements) == single_count == 4
    assert all("weekly_digests.content" not in statement for statement in statements)
    for item in items:
        latest_id, confirmed_id, delivery_id = expected[item.client_id]
        assert item.version_count == 4
        assert item.latest_digest_id == latest_id
        assert item.state == "newer_version_unconfirmed"
        assert item.reason == "already_exists"
        assert item.responsible_name == "Report owner"
        assert item.external_delivery.digest_id == confirmed_id
        assert item.internal_distribution.state == "failed"
        assert item.internal_distribution.delivery_id == delivery_id

    # Revoked capability immediately changes eligibility without relying on a
    # cached user object or mistaking the module's read permission for write.
    responsible.is_active = False
    await db_session.flush()
    assert (await preview_items(db_session, rows[:1]))[0].reason == "responsible_unavailable"
