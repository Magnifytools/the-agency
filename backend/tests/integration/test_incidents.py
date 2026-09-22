"""Canonical conditions, recipient isolation and decisions on PostgreSQL."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import noload

from backend.db.models import Notification, Task, TaskStatus, User, UserRole
from backend.schemas.incident import IncidentDecision
from backend.services.incidents import decide_incident, reconcile_recipient

NOW = datetime(2026, 9, 19, 10)


async def notifications(db, user_id):
    return list((await db.execute(select(Notification).options(noload("*")).where(Notification.user_id == user_id).order_by(Notification.id))).scalars())


async def task(db, user_id, **fields):
    row = Task(title="Compromiso de prueba", assigned_to=user_id, status=TaskStatus.pending, due_date=NOW - timedelta(days=1), **fields)
    db.add(row); await db.flush()
    return row


async def test_read_does_not_resolve_and_normal_aging_does_not_undo_snooze(db_session, admin_user):
    source = await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident, = await notifications(db_session, admin_user.id)
    incident.is_read = True
    await db_session.flush()
    until = NOW + timedelta(days=3)
    result = await decide_incident(db_session, admin_user.id, incident.id, IncidentDecision(revision=1, action="snooze", until=until.replace(tzinfo=timezone.utc)), now=NOW)
    assert result.state == "snoozed"
    assert result.href == f"/tasks?task={source.id}"
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(days=1))
    assert incident.incident_state == "snoozed"
    assert incident.incident_revision == 2
    assert len(await notifications(db_session, admin_user.id)) == 1
    await reconcile_recipient(db_session, admin_user.id, now=until)
    assert incident.incident_state == "active"
    assert incident.incident_revision == 3
    assert incident.is_read is True
    source.status = TaskStatus.completed
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=until)
    assert incident.incident_state == "resolved"
    assert incident.incident_resolution_reason == "condition_cleared"


async def test_dismissal_survives_same_cycle_but_new_deadline_is_a_new_condition(db_session, admin_user):
    source = await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    old, = await notifications(db_session, admin_user.id)
    await decide_incident(db_session, admin_user.id, old.id, IncidentDecision(revision=1, action="dismiss", reason="Revisado con el equipo"), now=NOW)
    source.title = "Texto actualizado"
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(days=1))
    assert old.incident_state == "dismissed"
    source.status = TaskStatus.completed
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(days=1))
    assert old.incident_state == "resolved"
    source.status = TaskStatus.pending
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(days=1))
    assert old.incident_state == "dismissed"  # Undo does not erase the decision.
    source.due_date -= timedelta(days=1)
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(days=1))
    rows = await notifications(db_session, admin_user.id)
    assert len(rows) == 2
    assert old.incident_state == "resolved"
    assert rows[-1].incident_state == "active"
    assert rows[-1].incident_dismissal_reason is None


async def test_waiting_followup_is_its_own_cycle_and_templates_are_not_work(db_session, admin_user):
    source = await task(db_session, admin_user.id)
    source.due_date = None
    source.status = TaskStatus.waiting
    source.follow_up_date = NOW.date()
    source.waiting_for = "Respuesta del cliente"
    await task(db_session, admin_user.id, is_recurring=True)
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident, = await notifications(db_session, admin_user.id)
    assert incident.type == "task_waiting_followup"
    assert "Respuesta del cliente" in incident.message
    source.follow_up_date += timedelta(days=2)
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    assert incident.incident_state == "resolved"


async def test_existing_legacy_check_is_adopted_without_activating_other_history(db_session, admin_user):
    source = await task(db_session, admin_user.id)
    legacy = Notification(user_id=admin_user.id, type="task_overdue", title="Aviso antiguo leído", entity_type="task", entity_id=source.id, is_read=True, created_at=NOW)
    activity = Notification(user_id=admin_user.id, type="task_assigned", title="Actividad pasada", entity_type="task", entity_id=source.id)
    db_session.add_all([legacy, activity]); await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    assert legacy.incident_state == "active"
    assert legacy.is_read is True
    assert activity.incident_state is None
    assert len(await notifications(db_session, admin_user.id)) == 2
    assert legacy.incident_detected_at == NOW


async def test_adoption_preserves_unknown_legacy_timezone_and_uses_observed_utc(db_session, admin_user):
    from backend.services.incidents import incident_response
    source = await task(db_session, admin_user.id)
    legacy_time = NOW + timedelta(hours=2)
    legacy = Notification(user_id=admin_user.id, type="task_overdue", title="Legacy", entity_type="task", entity_id=source.id, created_at=legacy_time)
    malformed = Notification(user_id=admin_user.id, type="task_overdue", title="Other domain", entity_type="project", entity_id=source.id, created_at=NOW)
    db_session.add_all([legacy, malformed]); await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    assert legacy.created_at == legacy_time
    assert incident_response(legacy).model_dump(mode="json")["created_at"] == "2026-09-19T10:00:00Z"
    assert malformed.incident_state is None
    assert len(await notifications(db_session, admin_user.id)) == 2


async def test_activity_cannot_count_or_mark_operational_incidents(admin_client, admin_user, db_session):
    source = await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident, = await notifications(db_session, admin_user.id)
    activity = Notification(user_id=admin_user.id, type="task_assigned", title="Actividad", entity_type="task", entity_id=source.id, is_read=False)
    db_session.add(activity); await db_session.commit()
    await decide_incident(db_session, admin_user.id, incident.id, IncidentDecision(revision=1, action="dismiss", reason="Revisado"), now=NOW)
    await db_session.commit()
    assert (await admin_client.get("/api/notifications/unread-count")).json() == {"count": 1}
    assert [item["id"] for item in (await admin_client.get("/api/notifications")).json()] == [activity.id]
    assert (await admin_client.put(f"/api/notifications/{incident.id}/read")).status_code == 404
    assert (await admin_client.put("/api/notifications/read-all")).status_code == 200
    await db_session.refresh(incident)
    assert incident.is_read is False
    assert incident.incident_state == "dismissed"
    assert (await admin_client.get("/api/notifications/unread-count")).json() == {"count": 0}


async def test_reconciler_waits_for_task_writer_and_rechecks_changed_source(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"source-race-{uuid4().hex}@test.local", full_name="Concurrency", hashed_password="test", role=UserRole.admin, is_active=True)
        db.add(actor); await db.flush()
        source = await task(db, actor.id)
        await db.commit()
        actor_id, task_id = actor.id, source.id
    async def reconcile():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            result = await reconcile_recipient(db, actor_id, now=NOW)
            await db.commit()
            return result
    pending = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as writer:
            locked = (await writer.execute(select(Task).options(noload("*")).where(Task.id == task_id).with_for_update())).scalar_one()
            locked.status = TaskStatus.completed
            await writer.flush()
            pending = asyncio.create_task(reconcile())
            await asyncio.sleep(0.1)
            assert not pending.done(), "Reconciliation must wait for the committed task state"
            await writer.commit()
        assert await asyncio.wait_for(pending, timeout=5) == {"created": 0, "changed": 0}
        async with AsyncSession(engine) as db:
            assert await notifications(db, actor_id) == []
    finally:
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        async with engine.begin() as conn:
            await conn.execute(delete(Notification).where(Notification.user_id == actor_id))
            await conn.execute(delete(Task).where(Task.id == task_id))
            await conn.execute(delete(User).where(User.id == actor_id))


async def test_http_reads_are_pure_and_permissions_hide_conditions_immediately(db_session, make_member_client, engine):
    member = await make_member_client([("tasks", True, False)])
    other = await make_member_client([("tasks", True, True)])
    await task(db_session, member.test_user.id)
    await reconcile_recipient(db_session, member.test_user.id, now=NOW)
    await db_session.commit()
    writes = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await member.get("/api/incidents")
        count = await member.get("/api/incidents/count")
        invisible = await other.get("/api/incidents")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert result.status_code == 200, result.text
    assert count.json() == {"count": 1}
    assert len(result.json()["items"]) == 1
    assert invisible.json()["items"] == []
    assert not writes
    permission = next(p for p in member.test_user.permissions if p.module == "tasks")
    permission.can_read = False
    await db_session.commit()
    assert (await member.get("/api/incidents/count")).json() == {"count": 0}
    assert (await member.get("/api/incidents")).json()["items"] == []
    await reconcile_recipient(db_session, member.test_user.id, now=NOW)
    incident, = await notifications(db_session, member.test_user.id)
    assert incident.incident_resolution_reason == "permission_lost"
    await member.aclose(); await other.aclose()


async def test_two_reconcilers_and_two_decisions_cannot_duplicate_or_overwrite(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"incidents-{uuid4().hex}@test.local", full_name="Concurrency", hashed_password="test", role=UserRole.admin, is_active=True)
        db.add(actor); await db.flush()
        source = await task(db, actor.id)
        await db.commit()
        actor_id, task_id = actor.id, source.id
    async def reconcile():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await reconcile_recipient(db, actor_id, now=NOW)
            await db.commit()
    try:
        await asyncio.wait_for(asyncio.gather(reconcile(), reconcile()), timeout=10)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            incident, = await notifications(db, actor_id)
            incident_id = incident.id
        async def decide(reason):
            async with AsyncSession(engine, expire_on_commit=False) as db:
                try:
                    response = await decide_incident(db, actor_id, incident_id, IncidentDecision(revision=1, action="dismiss", reason=reason), now=NOW)
                    await db.commit()
                    return response.dismissal_reason
                except HTTPException as exc:
                    await db.rollback()
                    assert exc.status_code == 409
                    return None
        results = await asyncio.wait_for(asyncio.gather(decide("Primera decisión"), decide("Otra decisión")), timeout=10)
        assert sum(value is not None for value in results) == 1
        async with AsyncSession(engine, expire_on_commit=False) as db:
            incident, = await notifications(db, actor_id)
            assert incident.incident_revision == 2
            assert incident.incident_dismissal_reason in results
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Notification).where(Notification.user_id == actor_id))
            await conn.execute(delete(Task).where(Task.id == task_id))
            await conn.execute(delete(User).where(User.id == actor_id))


async def test_closed_or_reassigned_sources_disappear_without_a_read_side_effect(admin_client, db_session, admin_user, monkeypatch):
    monkeypatch.setattr("backend.services.incidents.business_today", lambda **kwargs: NOW.date())
    source = await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 1}
    source.status = TaskStatus.completed
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 0}
    assert (await admin_client.get("/api/incidents")).json()["items"] == []
    incident, = await notifications(db_session, admin_user.id)
    assert incident.incident_state == "active"  # GET did not mutate it.
    source.status = TaskStatus.pending
    source.due_date -= timedelta(days=1)
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 0}  # old cycle is not today's commitment
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 1}


async def test_decision_replay_is_a_conflict_and_does_not_reapply_old_intent(admin_client, admin_user, db_session):
    await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.commit()
    incident, = await notifications(db_session, admin_user.id)
    request = {"revision": 1, "action": "dismiss", "reason": "Ya revisado"}
    first = await admin_client.post(f"/api/incidents/{incident.id}/decision", json=request)
    retry = await admin_client.post(f"/api/incidents/{incident.id}/decision", json=request)
    assert first.status_code == 200, first.text
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"]["current"]["revision"] == 2
    assert retry.json()["detail"]["current"]["state"] == "dismissed"
    assert (await admin_client.post(f"/api/incidents/{incident.id}/decision", json={"revision": 2, "action": "dismiss", "reason": " "})).status_code == 422


async def test_reconciliation_reads_stay_bounded_for_many_conditions(db_session, admin_user, engine):
    for _ in range(35):
        await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await reconcile_recipient(db_session, admin_user.id, now=NOW)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert result == {"created": 0, "changed": 0}
    # A fixed budget covers task/project/report collectors, regardless of count.
    assert len(statements) <= 10
    assert len(await notifications(db_session, admin_user.id)) == 35


async def test_migration_is_additive_concurrent_and_keeps_legacy_activity_inactive(engine):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from backend.startup.incident_schema import ensure_incident_schema
    schema = "incident_upgrade_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("CREATE TABLE notifications (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT)"))
            await conn.execute(text("INSERT INTO notifications SELECT n,1,'Historical notification' FROM generate_series(1,350) n"))
        await asyncio.gather(*(ensure_incident_schema(isolated) for _ in range(3)))
        async with isolated.begin() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM notifications")) == 350
            assert await conn.scalar(text("SELECT count(*) FROM notifications WHERE incident_state IS NOT NULL")) == 0
            assert await conn.scalar(text("SELECT count(*) FROM notifications WHERE title='Historical notification'")) == 350
    finally:
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_pages_keep_recipient_and_state_isolation(admin_client, admin_user, db_session, monkeypatch):
    monkeypatch.setattr("backend.services.incidents.business_today", lambda **kwargs: NOW.date())
    for _ in range(7):
        await task(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    rows = await notifications(db_session, admin_user.id)
    await decide_incident(db_session, admin_user.id, rows[0].id, IncidentDecision(revision=1, action="dismiss", reason="Ya revisado"), now=NOW)
    await db_session.commit()
    seen, cursor = [], None
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = await admin_client.get("/api/incidents", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [row.id for row in reversed(rows[1:])]
    dismissed = await admin_client.get("/api/incidents", params={"state": "dismissed"})
    assert [item["id"] for item in dismissed.json()["items"]] == [rows[0].id]
    assert (await admin_client.get("/api/incidents", params={"limit": 101})).status_code == 422
    assert (await admin_client.get("/api/incidents", params={"cursor": 0})).status_code == 422


async def test_worker_pages_recipients_recovers_failures_and_resolves_disabled_users(engine, monkeypatch):
    from backend.services import incidents
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = []
    async with factory() as db:
        for index in range(103):
            actor = User(email=f"scan-{uuid4().hex}@test.local", full_name=f"Scan {index}", hashed_password="test", role=UserRole.admin, is_active=True)
            db.add(actor); users.append(actor)
        await db.flush()
        ids = [actor.id for actor in users]
        for actor in (users[0], users[1], users[-1]):
            await task(db, actor.id)
        await reconcile_recipient(db, users[-1].id, now=NOW)
        users[-1].is_active = False
        await db.commit()
    original = incidents.reconcile_recipient
    attempted = []
    async def one_failure(db, user_id, **kwargs):
        attempted.append(user_id)
        result = await original(db, user_id, **kwargs)
        if user_id == ids[0]:
            raise RuntimeError("Synthetic failure after flush")
        return result
    monkeypatch.setattr(incidents, "reconcile_recipient", one_failure)
    try:
        result = await incidents.reconcile_all(factory, now=NOW)
        assert result["failed"] == 1
        assert all(attempted.count(user_id) == 1 for user_id in ids)
        async with factory() as db:
            assert await notifications(db, ids[0]) == []  # Failed recipient rolled back.
            good, = await notifications(db, ids[1])
            assert good.incident_state == "active"
            disabled, = await notifications(db, ids[-1])
            assert disabled.incident_state == "resolved"
            assert disabled.incident_resolution_reason == "permission_lost"
        monkeypatch.setattr(incidents, "reconcile_recipient", original)
        retry = await incidents.reconcile_all(factory, now=NOW)
        assert retry["failed"] == 0
        async with factory() as db:
            recovered, = await notifications(db, ids[0])
            assert recovered.incident_state == "active"
            assert len(await notifications(db, ids[1])) == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Notification).where(Notification.user_id.in_(ids)))
            await conn.execute(delete(Task).where(Task.assigned_to.in_(ids)))
            await conn.execute(delete(User).where(User.id.in_(ids)))
