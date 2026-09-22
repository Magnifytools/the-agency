"""B2 transactional occurrences, policy authority, civil clock and simulated transport."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, delete, update, func, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.api.deps import get_current_user
from backend.api.routes import communication_schedules as routes, google_calendar
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import (CommunicationSchedule as Schedule, CommunicationOccurrence as Occurrence, CommunicationRequest,
    Delivery, DeliveryAttempt, Notification, User, UserRole, UserPermission, Event, EventType, Task, TaskStatus, DiscordSettings)
from backend.services import scheduled_communications as svc, deliveries


@pytest_asyncio.fixture
async def fixture(engine, monkeypatch):
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("Real network forbidden")))
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/test")
    now = [datetime(2026, 9, 14, 8)]  # Monday 10:00 Madrid
    monkeypatch.setattr(svc, "utc_now_naive", lambda: now[0])
    monkeypatch.setattr(deliveries, "utc_now_naive", lambda: now[0])
    monkeypatch.setattr(routes, "utc_now_naive", lambda: now[0])
    monkeypatch.setattr(google_calendar, "utc_now_naive", lambda: now[0])
    monkeypatch.setattr(svc, "SCHEDULER_STARTED_AT", now[0] - timedelta(minutes=1))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        admin = User(email=f"b2admin-{uuid4()}@test.local", full_name="Schedule Admin", hashed_password="unused", role=UserRole.admin, is_active=True, google_calendar_connected=True)
        member = User(email=f"b2member-{uuid4()}@test.local", full_name="Schedule Member", hashed_password="unused", role=UserRole.member, is_active=True, google_calendar_connected=True)
        config = DiscordSettings(bot_token="synthetic-bot")
        db.add_all([admin, member, config]); await db.flush()
        db.add(UserPermission(user_id=member.id, module="tasks", can_read=True, can_write=True))
        await db.commit()
        ids = {"admin": admin.id, "member": member.id, "config": config.id}
    yield maker, ids, now
    async with maker() as db:
        for model in (DeliveryAttempt, Delivery, Occurrence, Schedule, CommunicationRequest, Notification, Event, Task):
            await db.execute(delete(model))
        await db.execute(delete(UserPermission).where(UserPermission.user_id.in_([admin.id, member.id])))
        await db.execute(delete(User).where(User.id.in_([admin.id, member.id])))
        await db.execute(delete(DiscordSettings).where(DiscordSettings.id == config.id))
        await db.commit()


def body(kind="morning", **overrides):
    values = dict(revision=0, enabled=True, channels=["in_app"], time="10:00", minutes_before=None, quiet_start=None, quiet_end=None)
    if kind == "meeting": values.update(channels=["extension"], time=None, minutes_before=30)
    if kind == "weekly": values.update(channels=["owner_dm"], time="08:00", destination_id="123456789")
    return routes.PolicyUpdate(**(values | overrides))


async def policy(fixture, kind="morning", identity="member", **kwargs):
    maker, ids, now = fixture
    async with maker() as db:
        result = await svc.save_policy(db, await svc.load_actor(db, ids[identity]), kind, body(kind, **kwargs))
        row = await db.scalar(select(Schedule).where(Schedule.policy_key == svc.policy_key(kind, ids[identity])))
        row.effective_from = now[0] - timedelta(days=1)
        await db.commit()
        return row.id, result


@asynccontextmanager
async def client(fixture, identity="member"):
    maker, ids, _ = fixture
    app = FastAPI()
    app.include_router(routes.router); app.include_router(google_calendar.router)
    async def session():
        async with maker() as db: yield db
    async def actor():
        async with maker() as db: return await svc.load_actor(db, ids[identity])
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http: yield http


async def count(maker, model):
    async with maker() as db: return await db.scalar(select(func.count()).select_from(model))


async def test_no_inferred_consent_legacy_disabled_and_negative_authority(fixture):
    maker, ids, _ = fixture
    async with client(fixture) as http:
        data = (await http.get("/api/communication-schedules")).json()
        assert len(data["policies"]) == 3
        assert all(p["state"] == "needs_review" and not p["enabled"] for p in data["policies"])
        assert (await http.get("/api/calendar/upcoming")).json() == []
        assert (await http.put("/api/calendar/alerts", json={})).status_code == 409
        assert (await http.put("/api/communication-schedules/weekly", json=body("weekly").model_dump())).status_code == 403
        assert (await http.put("/api/communication-schedules/meeting", json=body("meeting", channels=["owner_dm"]).model_dump())).status_code == 422
        assert (await http.get("/api/communication-schedules/discord-configuration")).status_code == 403
    await svc.run_scheduler_once(maker)
    assert await count(maker, Occurrence) == 0
    assert await count(maker, Schedule) == 0


async def test_two_schedulers_restart_prepare_once_per_channel(fixture):
    maker, _, now = fixture
    await policy(fixture, channels=["in_app", "team_webhook"])
    now[0] += timedelta(minutes=12)  # beyond old 5min window
    await asyncio.gather(svc.run_scheduler_once(maker), svc.run_scheduler_once(maker))
    await svc.run_scheduler_once(maker)
    assert await count(maker, Occurrence) == 2
    assert await count(maker, Notification) == 1
    assert await count(maker, CommunicationRequest) == 1
    assert await count(maker, Delivery) == 1
    async with maker() as db:
        receipt = await db.scalar(select(Delivery))
        assert receipt.status == "pending"


async def test_commit_failure_rolls_back_snapshot_and_notification(fixture):
    maker, _, now = fixture
    ident, _ = await policy(fixture, channels=["team_webhook"])
    async with maker() as db:
        await svc.plan_policy(db, await db.get(Schedule, ident), now[0]); await db.commit()
    async with maker() as db:
        occurrence = await db.scalar(select(Occurrence))
        await svc.prepare_occurrence(db, occurrence, now[0])
        db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
        with pytest.raises(RuntimeError): await db.commit()
        await db.rollback()
    assert await count(maker, CommunicationRequest) == 0
    assert await count(maker, Delivery) == 0
    await svc.run_scheduler_once(maker)
    assert await count(maker, Delivery) == 1


async def test_disabled_or_changed_policy_blocks_after_first_provider_part(fixture, monkeypatch):
    maker, ids, _ = fixture
    ident, _ = await policy(fixture, channels=["team_webhook"])
    monkeypatch.setattr(svc, "render_occurrence", AsyncMock(return_value="x" * 4100))
    await svc.run_scheduler_once(maker)
    calls = []
    async def provider(request):
        calls.append(request)
        async with maker() as db:
            await db.execute(update(Schedule).where(Schedule.id == ident).values(enabled=False)); await db.commit()
        return httpx.Response(200, json={"id": "123", "channel_id": "456"})
    await deliveries.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(calls) == 1
    async with maker() as db:
        row = await db.scalar(select(Delivery)); assert row.status == "cancelled"
        assert (await deliveries.latest_attempt(db, row.id)).steps[0]["status"] == "sent"


async def test_quiet_midnight_dst_and_expiry(fixture):
    maker, _, now = fixture
    ident, _ = await policy(fixture, quiet_start="22:00", quiet_end="11:00")
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 0
    now[0] = datetime(2026, 9, 14, 9)  #11 local
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 1
    assert svc.local_instant(date(2026, 3, 29), "02:30") == datetime(2026, 3, 29, 1)
    assert svc.local_instant(date(2026, 10, 25), "02:30") == datetime(2026, 10, 25, 0, 30)
    async with maker() as db:
        p = await db.get(Schedule, ident)
        assert svc.quiet_until(p, datetime(2026, 9, 14, 23)) == datetime(2026, 9, 15, 9)
    now[0] = datetime(2026, 9, 15, 22)
    await svc.run_scheduler_once(maker)
    async with maker() as db:
        latest = await db.scalar(select(Occurrence).where(Occurrence.period_start == date(2026, 9, 15)))
        assert latest.state == "expired"


async def test_repeated_hour_does_not_release_in_app_notice_during_quiet(fixture):
    maker, ids, now = fixture
    policy_id, _ = await policy(fixture, quiet_start="02:00", quiet_end="02:30")
    now[0] = datetime(2026, 10, 25, 1, 15)  # Second 02:15 in Madrid.
    async with maker() as db:
        occurrence = Occurrence(
            occurrence_key="quiet-second-fold", schedule_id=policy_id,
            recipient_id=ids["member"], kind="morning", channel="in_app",
            period_start=date(2026, 10, 25), period_end=date(2026, 10, 25),
            due_at=datetime(2026, 10, 25, 1), expires_at=datetime(2026, 10, 25, 1, 45),
            state="planned",
        )
        db.add(occurrence)
        await db.flush()
        await svc.prepare_occurrence(db, occurrence, now[0])
        assert occurrence.state == "planned"
        assert occurrence.notification_id is None
        await db.commit()
    assert await count(maker, Notification) == 0


async def test_meeting_without_tasks_legacy_reschedule_and_extension_prefs(fixture):
    maker, ids, now = fixture
    await policy(fixture, "meeting")
    async with maker() as db:
        event = Event(user_id=ids["member"], event_type=EventType.meeting, title="Only meeting", start_time=datetime(2026, 9, 14, 10, 25))
        legacy = Event(user_id=ids["member"], event_type=EventType.meeting, title="Old receipt unknown", start_time=datetime(2026, 9, 14, 10, 20), alert_sent_at=now[0])
        db.add_all([event, legacy]); await db.commit(); event_id = event.id
        from backend.services.daily_reminders import generate_morning_plan
        text_value = await generate_morning_plan(db, await svc.load_actor(db, ids["member"]), day=date(2026, 9, 14))
        assert "Only meeting" in text_value
    await svc.run_scheduler_once(maker)
    async with client(fixture) as http:
        data = (await http.get("/api/communication-schedules/extension-upcoming")).json()
        assert len(data["occurrences"]) == 1
        assert data["occurrences"][0]["minutes_until"] == 25
        assert data["occurrences"][0]["start_time"].endswith("Z")
    async with maker() as db:
        await db.execute(update(Event).where(Event.id == event_id).values(start_time=datetime(2026, 9, 14, 11))); await db.commit()
    async with client(fixture) as http:
        assert (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"] == []
        history = (await http.get("/api/communication-schedules/history")).json()
        assert any(row["state"] == "blocked" for row in history)
    now[0] += timedelta(minutes=35)
    await svc.run_scheduler_once(maker)
    async with client(fixture) as http:
        data = (await http.get("/api/communication-schedules/extension-upcoming")).json()
        assert len(data["occurrences"]) == 1
        previous = data["policy"]
        response = await http.put("/api/communication-schedules/meeting", json=body("meeting", revision=previous["revision"], enabled=False).model_dump())
        assert response.status_code == 200
        assert (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"] == []


async def test_weekly_delayed_snapshot_closed_period_and_explicit_recipient(fixture, monkeypatch):
    maker, ids, now = fixture
    now[0] = datetime(2026, 9, 19, 7)
    ident, _ = await policy(fixture, "weekly", identity="admin")
    from backend.services import weekly_report_service
    renderer = AsyncMock(return_value="Closed week")
    monkeypatch.setattr(weekly_report_service, "generate_weekly_report", renderer)
    now[0] += timedelta(days=1)
    await svc.run_scheduler_once(maker)
    assert renderer.call_args.kwargs == {"period_start": date(2026, 9, 14), "period_end": date(2026, 9, 18)}
    async with maker() as db:
        row = await db.scalar(select(Delivery)); assert "123456789" in row.payload["destination_label"]
        await db.execute(update(Schedule).where(Schedule.id == ident).values(destination_id="987654321")); await db.commit()
    provider = AsyncMock(side_effect=AssertionError("must not send to changed recipient"))
    await deliveries.run_once(maker, transport=httpx.MockTransport(provider))
    assert provider.call_count == 0
    async with maker() as db: assert (await db.scalar(select(Delivery))).status == "cancelled"


async def test_paused_flag_and_permission_revocation_prevent_send(fixture, monkeypatch):
    maker, ids, now = fixture
    await policy(fixture, channels=["team_webhook"])
    await svc.run_scheduler_once(maker)
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", False)
    async with maker() as db: assert await deliveries.claim(db) is None
    async with maker() as db: assert (await db.scalar(select(Delivery))).status == "pending"
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", True)
    now[0] += timedelta(minutes=2)
    async with maker() as db:
        await db.execute(delete(UserPermission).where(UserPermission.user_id == ids["member"])); await db.commit()
    async with maker() as db: assert await deliveries.claim(db) is None
    async with maker() as db: assert (await db.scalar(select(Delivery))).status == "cancelled"


async def test_policy_cas_and_configuration_never_returns_secrets(fixture):
    maker, _, _ = fixture
    async with client(fixture, "admin") as http:
        url = "/api/communication-schedules/discord-configuration"
        response = await http.put(url, json={"webhook_url": "https://discord.com/api/webhooks/123/secret-test", "bot_token": "secret-bot"})
        assert response.status_code == 200
        assert response.json() == {"webhook_configured": True, "bot_token_configured": True}
        assert "secret" not in (await http.get(url)).text
        async with maker() as db:
            ds = await db.scalar(select(DiscordSettings)); assert ds.webhook_url.startswith("v1:") and ds.bot_token.startswith("v1:")
    async with client(fixture) as http:
        url = "/api/communication-schedules/morning"
        a, b = await asyncio.gather(http.put(url, json=body().model_dump()), http.put(url, json=body().model_dump()))
        assert sorted([a.status_code, b.status_code]) == [200, 409]


async def test_configuration_failure_local_channel_still_delivers_and_error_is_visible(fixture, monkeypatch):
    maker, _, _ = fixture
    await policy(fixture, channels=["in_app", "team_webhook"])
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "")
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 1
    assert await count(maker, Delivery) == 0
    async with client(fixture) as http:
        rows = (await http.get("/api/communication-schedules/history")).json()
        assert any(r["state"] == "blocked" and "webhook" in r["reason"] for r in rows)


async def test_render_failure_leaves_no_partial_source_and_retry_preserves_occurrence(fixture, monkeypatch):
    maker, _, _ = fixture
    await policy(fixture, channels=["team_webhook"])
    renderer = AsyncMock(side_effect=ValueError("sensitive provider detail"))
    monkeypatch.setattr(svc, "render_occurrence", renderer)
    await svc.run_scheduler_once(maker)
    assert await count(maker, CommunicationRequest) == 0
    async with maker() as db:
        row = await db.scalar(select(Occurrence)); ident = row.id
        assert row.state == "blocked" and "sensitive" not in row.reason
    renderer.side_effect = None; renderer.return_value = "Ready after recovery"
    await svc.run_scheduler_once(maker)
    async with maker() as db:
        row = await db.scalar(select(Occurrence)); assert row.id == ident and row.state == "ready"
    assert await count(maker, Delivery) == 1


async def test_quiet_change_between_parts_defers_without_repeating_prefix(fixture, monkeypatch):
    maker, _, now = fixture
    ident, _ = await policy(fixture, channels=["team_webhook"])
    monkeypatch.setattr(svc, "render_occurrence", AsyncMock(return_value="x" * 4100))
    await svc.run_scheduler_once(maker)
    calls = []
    async def provider(request):
        calls.append(request)
        if len(calls) == 1:
            async with maker() as db:
                await db.execute(update(Schedule).where(Schedule.id == ident).values(quiet_start="09:00", quiet_end="11:00")); await db.commit()
        return httpx.Response(200, json={"id": str(100 + len(calls)), "channel_id": "456"})
    await deliveries.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(calls) == 1
    async with maker() as db:
        row = await db.scalar(select(Delivery)); assert row.status == "pending" and row.available_at == datetime(2026, 9, 14, 9)
    now[0] = datetime(2026, 9, 14, 9)
    await deliveries.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(calls) == 3
    async with maker() as db: assert (await db.scalar(select(Delivery))).status == "sent"


async def test_upgrade_preserves_event_ids_and_scopes_external_ids(fixture, engine):
    maker, ids, _ = fixture
    from backend.startup.delivery_schema import ensure_delivery_schema
    from backend.startup.readiness import check_database_ready
    async with maker() as db:
        event = Event(user_id=ids["member"], title="Legacy", event_type=EventType.meeting, start_time=datetime(2026, 9, 14, 10), source="google", google_event_id="shared-external")
        db.add(event); await db.commit(); original_id = event.id
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX uq_events_google_scope"))
        await conn.execute(text("ALTER TABLE events DROP COLUMN source_calendar_id"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN google_calendar_synced_at"))
        await conn.execute(text("ALTER TABLE events ADD CONSTRAINT legacy_google_unique UNIQUE(google_event_id)"))
        await conn.run_sync(Occurrence.__table__.drop)
        await conn.run_sync(Schedule.__table__.drop)
    await asyncio.gather(ensure_delivery_schema(engine), ensure_delivery_schema(engine))
    await check_database_ready(engine)
    async with maker() as db:
        assert (await db.get(Event, original_id)).title == "Legacy"
        db.add(Event(user_id=ids["admin"], title="Separate owner", event_type=EventType.meeting, start_time=datetime(2026, 9, 14, 10), source="google", source_calendar_id="primary", google_event_id="shared-external"))
        await db.commit()
    async with engine.begin() as conn: await conn.execute(text("DROP INDEX uq_communication_occurrence_key"))
    with pytest.raises(RuntimeError): await check_database_ready(engine)
    async with engine.begin() as conn: await conn.execute(text("CREATE UNIQUE INDEX uq_communication_occurrence_key ON communication_occurrences(occurrence_key)"))


async def test_calendar_reconciliation_is_complete_user_window_scoped_and_civil(fixture, monkeypatch):
    maker, ids, now = fixture
    # Match the controlled sync window, while provider payloads use UTC.
    day = now[0].date()
    local_start = datetime.combine(day, datetime.min.time())
    async with maker() as db:
        user = await db.get(User, ids["member"]); user.google_refresh_token = "synthetic"; user.google_calendar_id = "primary"
        existing = Event(user_id=user.id, title="Before", event_type=EventType.meeting, start_time=local_start + timedelta(hours=11), source="google", source_calendar_id="primary", google_event_id="kept")
        removed = Event(user_id=user.id, title="Cancelled", event_type=EventType.meeting, start_time=local_start + timedelta(hours=12), source="google", source_calendar_id="primary", google_event_id="removed")
        other = Event(user_id=ids["admin"], title="Other owner", event_type=EventType.meeting, start_time=local_start + timedelta(hours=12), source="google", source_calendar_id="primary", google_event_id="removed")
        other_calendar = Event(user_id=user.id, title="Other calendar", event_type=EventType.meeting, start_time=local_start + timedelta(hours=12), source="google", source_calendar_id="other", google_event_id="removed")
        manual = Event(user_id=user.id, title="Manual", event_type=EventType.meeting, start_time=local_start + timedelta(hours=12))
        outside = Event(user_id=user.id, title="Outside", event_type=EventType.meeting, start_time=local_start + timedelta(days=10), source="google", source_calendar_id="primary", google_event_id="outside")
        db.add_all([existing, removed, other, other_calendar, manual, outside]); await db.commit()
        preserved = [e.id for e in (other, other_calendar, manual, outside)]
        kept_id, removed_id = existing.id, removed.id
    payload = [{"google_event_id": "kept", "title": "Rescheduled", "start_time": f"{day.isoformat()}T09:30:00Z"}, {"google_event_id": "removed", "cancelled": True}]
    monkeypatch.setattr(google_calendar, "fetch_events", lambda *a, **k: payload)
    async with maker() as db:
        assert await google_calendar.sync_user_events(db, await db.get(User, ids["member"])) == 1
    async with maker() as db:
        assert await db.get(Event, removed_id) is None
        assert all([await db.get(Event, ident) is not None for ident in preserved])
        kept = await db.get(Event, kept_id)
        from backend.services.temporal import business_zone
        expected = datetime.fromisoformat(f"{day.isoformat()}T09:30:00+00:00").astimezone(business_zone()).replace(tzinfo=None)
        assert kept.title == "Rescheduled" and kept.start_time == expected
    def failure(*a, **k): raise RuntimeError("partial page failed")
    monkeypatch.setattr(google_calendar, "fetch_events", failure)
    async with maker() as db:
        with pytest.raises(HTTPException) as error: await google_calendar.sync_user_events(db, await db.get(User, ids["member"]))
        assert error.value.status_code == 502
    async with maker() as db: assert await db.get(Event, kept_id) is not None


async def test_scheduled_scope_cannot_bypass_authorization(fixture):
    maker, ids, _ = fixture
    await policy(fixture, channels=["team_webhook"])
    await svc.run_scheduler_once(maker)
    async with maker() as db:
        source = await db.scalar(select(CommunicationRequest))
        source.scope = "team"
        await db.commit()
        with pytest.raises(HTTPException):
            await svc.authorize_scheduled(db, source, await svc.load_actor(db, ids["member"]))


async def test_meeting_reenable_changes_due_without_replaying_same_identity(fixture):
    maker, ids, now = fixture
    async with maker() as db:
        # Manual meetings do not depend on a Google connection.
        actor = await svc.load_actor(db, ids["member"])
        actor.google_calendar_connected = False
        db.add(Event(user_id=actor.id, title="Manual forthcoming", event_type=EventType.meeting,
                     start_time=datetime(2026, 9, 14, 10, 25)))
        await db.commit()
        await svc.save_policy(db, actor, "meeting", body("meeting", channels=["extension", "in_app"]))
    await svc.run_scheduler_once(maker)
    async with client(fixture) as http:
        initial = (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"]
        assert len(initial) == 1 and initial[0]["start_time"] == "2026-09-14T08:25:00Z"
        ident = initial[0]["occurrence_id"]
        now[0] += timedelta(minutes=1)
        assert (await http.put("/api/communication-schedules/meeting", json=body("meeting", revision=1, enabled=False, channels=["extension", "in_app"]).model_dump())).status_code == 200
        assert (await http.put("/api/communication-schedules/meeting", json=body("meeting", revision=2, minutes_before=5, channels=["extension", "in_app"]).model_dump())).status_code == 200
        await svc.run_scheduler_once(maker)
        assert (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"] == []
        now[0] += timedelta(minutes=19)
        await svc.run_scheduler_once(maker)
        current = (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"]
        assert [row["occurrence_id"] for row in current] == [ident]
    assert await count(maker, Occurrence) == 2
    assert await count(maker, CommunicationRequest) == 1
    assert await count(maker, Notification) == 1  # already delivered in-app is never reset
    async with maker() as db:
        assert (await db.get(Occurrence, ident)).due_at == now[0]


async def test_google_meeting_waits_for_complete_post_restart_sync(fixture, monkeypatch):
    maker, ids, now = fixture
    await policy(fixture, "meeting", channels=["in_app", "extension"])
    async with maker() as db:
        actor = await db.get(User, ids["member"])
        actor.google_refresh_token = "synthetic"
        actor.google_calendar_id = "primary"
        actor.google_calendar_synced_at = now[0] - timedelta(minutes=2)
        db.add(Event(user_id=actor.id, title="Cancelled during downtime", event_type=EventType.meeting,
                     start_time=datetime(2026, 9, 14, 10, 25), source="google", source_calendar_id="primary", google_event_id="cancelled"))
        await db.commit()
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 0
    def failure(*a, **k): raise RuntimeError("second page failed")
    monkeypatch.setattr(google_calendar, "fetch_events", failure)
    async with maker() as db:
        with pytest.raises(HTTPException): await google_calendar.sync_user_events(db, await db.get(User, ids["member"]))
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 0
    async with client(fixture) as http:
        assert (await http.get("/api/calendar/status")).json()["last_synced_at"] == "2026-09-14T07:58:00Z"
        assert (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"] == []
    monkeypatch.setattr(google_calendar, "fetch_events", lambda *a, **k: [])
    async with maker() as db:
        await google_calendar.sync_user_events(db, await db.get(User, ids["member"]))
    await svc.run_scheduler_once(maker)
    assert await count(maker, Event) == 0 and await count(maker, Notification) == 0
    payload = [{"google_event_id": "live", "title": "Verified upcoming", "start_time": "2026-09-14T08:25:00Z"}]
    monkeypatch.setattr(google_calendar, "fetch_events", lambda *a, **k: payload)
    async with maker() as db:
        await google_calendar.sync_user_events(db, await db.get(User, ids["member"]))
    await svc.run_scheduler_once(maker)
    assert await count(maker, Notification) == 1
    async with client(fixture) as http:
        assert len((await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"]) == 1
        now[0] += timedelta(minutes=21)
        assert (await http.get("/api/communication-schedules/extension-upcoming")).json()["occurrences"] == []


async def test_sync_commit_failure_cannot_mark_calendar_fresh(fixture, monkeypatch):
    maker, ids, now = fixture
    monkeypatch.setattr(google_calendar, "fetch_events", lambda *a, **k: [])
    async with maker() as db:
        user = await db.get(User, ids["member"])
        user.google_refresh_token = "synthetic"
        await db.commit()
        db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
        with pytest.raises(RuntimeError): await google_calendar.sync_user_events(db, user)
        await db.rollback()
    async with maker() as db:
        assert (await db.get(User, ids["member"])).google_calendar_synced_at is None
