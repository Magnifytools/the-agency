"""PostgreSQL coverage for the month-start notice of undelivered monthly digests."""
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    Notification,
    User,
    UserPermission,
    UserRole,
    WeeklyDigest,
)
from backend.services.incident_report_conditions import collect_report_conditions, report_visibility_clause
from backend.services.incidents import reconcile_recipient

NOW = datetime(2026, 10, 1, 8)  # noqa: DTZ001 - first business day of October
SEPT = (date(2026, 9, 1), date(2026, 9, 30))


async def _member(db, *, write=True):
    user = User(email=f"monthly-{uuid4().hex}@test.local", full_name="Responsable", hashed_password="x", role=UserRole.member, is_active=True)
    db.add(user)
    await db.flush()
    db.add(UserPermission(user_id=user.id, module="digests", can_read=True, can_write=write))
    await db.flush()
    return user


async def _client(db, responsible, *, weekly=False, monthly=True, status=ClientStatus.active, internal=False):
    client = Client(name=f"Cliente {uuid4().hex[:8]}", status=status, is_internal=internal)
    db.add(client)
    await db.flush()
    db.add(ClientReportPolicy(client_id=client.id, weekly_enabled=weekly, monthly_enabled=monthly, responsible_user_id=responsible.id))
    await db.flush()
    return client


async def _digest(db, client, author, *, offset=0):
    digest = WeeklyDigest(client_id=client.id, period_start=SEPT[0], period_end=SEPT[1], created_by=author.id,
                          created_at=NOW - timedelta(days=1) + timedelta(minutes=offset))
    db.add(digest)
    await db.flush()
    return digest


async def _event(db, digest, actor, action, *, offset=0):
    db.add(DigestExternalDeliveryEvent(digest_id=digest.id, action=action, actor_id=actor.id, request_key=uuid4().hex,
                                       request_hash="a" * 64, created_at=NOW + timedelta(minutes=offset)))
    await db.flush()


async def _unsent(db, user_id, client_id, now=NOW):
    return [c for c in (await collect_report_conditions(db, user_id, now)).values() if c.kind == "report_unsent" and c.entity_id == client_id]


async def _notice(db, user_id, client_id):
    return (await db.execute(select(Notification).where(
        Notification.user_id == user_id, Notification.type == "report_unsent", Notification.entity_id == client_id,
    ))).scalar_one()


async def test_admin_hears_about_missing_month_and_responsible_only_once_a_version_exists(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)

    [notice] = await _unsent(db_session, admin_user.id, client.id)
    assert notice.key == f"report_unsent:client:{client.id}:monthly:2026-09-01:2026-09-30"
    assert notice.message == "Falta preparar y entregar el resumen de septiembre de 2026."
    assert notice.href == f"/digests?client_id={client.id}&period_start=2026-09-01&period_end=2026-09-30"

    # The responsible is already told to prepare it (report_pending): no second notice.
    owner_conditions = await collect_report_conditions(db_session, owner.id, NOW)
    assert [c.kind for c in owner_conditions.values() if c.entity_id == client.id] == ["report_pending"]

    await _digest(db_session, client, owner)
    latest = await _digest(db_session, client, owner, offset=5)
    [owner_notice] = await _unsent(db_session, owner.id, client.id)
    assert owner_notice.href == f"/digests/{latest.id}/edit"
    assert f"versión #{latest.id}" in owner_notice.message
    [admin_notice] = await _unsent(db_session, admin_user.id, client.id)
    # Same cycle: a dismissal holds while the month stays undelivered.
    assert admin_notice.key == notice.key and admin_notice.fingerprint == notice.fingerprint


async def test_confirmed_delivery_of_any_version_clears_it_and_revocation_reopens(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    old = await _digest(db_session, client, owner)
    await _digest(db_session, client, owner, offset=5)

    await _event(db_session, old, owner, ExternalDeliveryAction.confirmed)
    assert await _unsent(db_session, admin_user.id, client.id) == []
    assert await _unsent(db_session, owner.id, client.id) == []

    await _event(db_session, old, owner, ExternalDeliveryAction.revoked, offset=1)
    assert len(await _unsent(db_session, admin_user.id, client.id)) == 1


async def test_only_active_external_clients_with_enabled_monthly_policy(db_session, admin_user):
    owner = await _member(db_session)
    excluded = [
        await _client(db_session, owner, weekly=True, monthly=False),
        await _client(db_session, owner, monthly=False),
        await _client(db_session, owner, internal=True),
        await _client(db_session, owner, status=ClientStatus.finished),
    ]
    for client in excluded:
        assert await _unsent(db_session, admin_user.id, client.id) == []


async def test_responsible_needs_digest_write_and_other_members_never_see_it(db_session):
    reader = await _member(db_session, write=False)
    client = await _client(db_session, reader)
    await _digest(db_session, client, reader)
    assert await _unsent(db_session, reader.id, client.id) == []
    stranger = await _member(db_session)
    assert await _unsent(db_session, stranger.id, client.id) == []


async def test_reconcile_resolves_when_delivery_is_confirmed(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    digest = await _digest(db_session, client, owner)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident = await _notice(db_session, admin_user.id, client.id)
    assert incident.incident_state == "active"
    current = report_visibility_clause(admin_user.id, current_only=True, now=NOW)
    assert await db_session.scalar(select(Notification.id).where(Notification.id == incident.id, current)) == incident.id

    await _event(db_session, digest, owner, ExternalDeliveryAction.confirmed)
    # Live visibility hides it before the job runs; history keeps it.
    assert await db_session.scalar(select(Notification.id).where(Notification.id == incident.id, current)) is None
    history = report_visibility_clause(admin_user.id, current_only=False, now=NOW)
    assert await db_session.scalar(select(Notification.id).where(Notification.id == incident.id, history)) == incident.id
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.refresh(incident)
    assert incident.incident_state == "resolved"
    assert incident.incident_resolution_reason == "condition_cleared"


async def test_next_month_replaces_the_notice(db_session, admin_user):
    owner = await _member(db_session)
    client = await _client(db_session, owner)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    old = await _notice(db_session, admin_user.id, client.id)
    november = datetime(2026, 11, 2, 8)  # noqa: DTZ001
    current = report_visibility_clause(admin_user.id, current_only=True, now=november)
    assert await db_session.scalar(select(Notification.id).where(Notification.id == old.id, current)) is None
    [october] = await _unsent(db_session, admin_user.id, client.id, now=november)
    assert october.key == f"report_unsent:client:{client.id}:monthly:2026-10-01:2026-10-31"
