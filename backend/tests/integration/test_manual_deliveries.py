"""B1: real PostgreSQL transactions, synthetic provider only."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, select, update, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload, noload

from backend.api.deps import get_current_user
from backend.api.routes import deliveries as delivery_routes, discord, pm
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import CommunicationRequest, Delivery, DeliveryAttempt, DiscordSettings, Task, TaskStatus, User, UserPermission, UserRole
from backend.services import deliveries as svc, manual_communications as manual
from backend.services.temporal import utc_now_naive


@pytest_asyncio.fixture
async def fixture(engine, monkeypatch):
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(side_effect=AssertionError("Real network forbidden in tests")))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/test-only")
    monkeypatch.setattr(settings, "DISCORD_OWNER_USER_ID", "123456789")
    async with maker() as db:
        admin = User(email=f"manual-admin-{uuid4()}@test.local", full_name="Admin", hashed_password="unused", role=UserRole.admin, is_active=True)
        member = User(email=f"manual-member-{uuid4()}@test.local", full_name="Member", hashed_password="unused", role=UserRole.member, is_active=True)
        config = DiscordSettings(bot_token="synthetic-bot")
        db.add_all([admin, member, config])
        await db.flush()
        db.add(UserPermission(user_id=member.id, module="pm", can_read=True, can_write=True))
        await db.commit()
        ids = {"admin": admin.id, "member": member.id, "config": config.id}
    yield maker, ids
    async with maker() as db:
        delivery_ids = select(Delivery.id).where(Delivery.source_kind == "communication")
        await db.execute(delete(DeliveryAttempt).where(DeliveryAttempt.delivery_id.in_(delivery_ids)))
        await db.execute(delete(Delivery).where(Delivery.source_kind == "communication"))
        await db.execute(delete(CommunicationRequest))
        await db.execute(delete(Task).where(Task.created_by.in_([ids["admin"], ids["member"]])))
        await db.execute(delete(UserPermission).where(UserPermission.user_id.in_([ids["admin"], ids["member"]])))
        await db.execute(delete(User).where(User.id.in_([ids["admin"], ids["member"]])))
        await db.execute(delete(DiscordSettings).where(DiscordSettings.id == ids["config"]))
        await db.commit()


async def actor(db, ident):
    return await db.scalar(select(User).where(User.id == ident).options(selectinload(User.permissions), noload(User.tasks)))


@asynccontextmanager
async def client(fixture, identity="admin"):
    maker, ids = fixture
    app = FastAPI()
    for router in (discord.router, delivery_routes.router, pm.router):
        app.include_router(router)
    async def session():
        async with maker() as db:
            yield db
    async def current_user():
        async with maker() as db:
            user = await actor(db, ids[identity])
            if not user.is_active:
                raise HTTPException(403)
            return user
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = current_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


def payload(kind="custom", content="Reviewed content", scope="team"):
    return dict(kind=kind, scope=scope, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20), title="Reviewed title", content=content)


async def queue(fixture, *, identity="admin", **kwargs):
    maker, ids = fixture
    async with maker() as db:
        return await manual.enqueue_request(db, await actor(db, ids[identity]), **payload(**kwargs))


async def state(fixture, ident):
    maker, _ = fixture
    async with maker() as db:
        row = await db.get(Delivery, ident)
        return row, await svc.latest_attempt(db, ident)


class Provider:
    def __init__(self, fail_at=None, status=403, timeout=False):
        self.calls, self.fail_at, self.status, self.timeout = [], fail_at, status, timeout
    def __call__(self, request):
        self.calls.append(request)
        if len(self.calls) == self.fail_at:
            if self.timeout:
                raise httpx.ReadTimeout("simulated", request=request)
            return httpx.Response(self.status, json={"retry_after": 1})
        return httpx.Response(200, json={"id": str(100 + len(self.calls)), "channel_id": "101"})


async def test_double_click_and_two_workers_keep_one_manual_intent(fixture):
    maker, _ = fixture
    first, second = await asyncio.gather(queue(fixture), queue(fixture))
    assert first["delivery_id"] == second["delivery_id"]
    assert first["source_kind"] == "communication" and first["success"] is False
    provider = Provider()
    await asyncio.gather(*(svc.run_once(maker, transport=httpx.MockTransport(provider)) for _ in range(2)))
    assert len(provider.calls) == 1
    assert (await state(fixture, first["delivery_id"]))[0].status == "sent"


async def test_staging_does_not_commit_and_failed_commit_rolls_back_both(fixture, monkeypatch):
    maker, ids = fixture
    async with maker() as db:
        commit = AsyncMock(side_effect=RuntimeError("failed commit"))
        monkeypatch.setattr(db, "commit", commit)
        row = await manual.stage_request(db, await actor(db, ids["admin"]), **payload())
        commit.assert_not_awaited()
        async with maker() as observer:
            assert await observer.get(Delivery, row.id) is None
            assert await observer.get(CommunicationRequest, row.source_id) is None
        with pytest.raises(RuntimeError):
            await db.commit()
    async with maker() as db:
        assert await db.scalar(select(CommunicationRequest.id)) is None
        assert await db.scalar(select(Delivery.id).where(Delivery.source_kind == "communication")) is None


async def test_dm_partial_timeout_is_uncertain_and_never_replayed(fixture):
    maker, _ = fixture
    receipt = await queue(fixture, kind="weekly_report", content="x" * 2200)
    provider = Provider(fail_at=3, timeout=True)
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, attempt = await state(fixture, receipt["delivery_id"])
    assert row.status == "uncertain" and [s["status"] for s in attempt.steps] == ["sent", "sent", "uncertain"]
    assert attempt.steps[0]["channel_id"] == "101" and "message_id" not in attempt.steps[0]
    assert attempt.steps[1]["message_id"] == "102"
    assert provider.calls[0].url.path == "/api/v10/users/@me/channels"
    assert provider.calls[1].url.path == "/api/v10/channels/101/messages"
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(provider.calls) == 3
    assert (await queue(fixture, kind="weekly_report", content="x" * 2200))["delivery_id"] == row.id
    with pytest.raises(HTTPException) as err:
        await queue(fixture, kind="weekly_report", content="changed")
    assert err.value.status_code == 409


async def test_dm_rejected_part_retry_keeps_channel_and_confirmed_prefix(fixture):
    maker, _ = fixture
    receipt = await queue(fixture, kind="weekly_report", content="x" * 2200)
    await svc.run_once(maker, transport=httpx.MockTransport(Provider(fail_at=3)))
    async with maker() as db:
        row = await db.get(Delivery, receipt["delivery_id"])
        await svc.retry(db, row, await db.get(CommunicationRequest, row.source_id))
    provider = Provider()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, attempt = await state(fixture, receipt["delivery_id"])
    assert row.status == "sent" and len(provider.calls) == 1
    assert attempt.steps[1]["message_id"] == "102"
    assert provider.calls[0].url.path == "/api/v10/channels/101/messages"


async def test_provider_acceptance_then_receipt_commit_failure_has_no_blind_retry(fixture, monkeypatch):
    maker, _ = fixture
    receipt = await queue(fixture, kind="weekly_report")
    original = AsyncSession.commit
    async def broken(db):
        if any(isinstance(row, DeliveryAttempt) and any(step["status"] == "sent" and step["kind"] == "dm_body" for step in row.steps) for row in db.dirty):
            raise RuntimeError("receipt commit lost")
        await original(db)
    monkeypatch.setattr(AsyncSession, "commit", broken)
    provider = Provider()
    with pytest.raises(RuntimeError):
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
    monkeypatch.setattr(AsyncSession, "commit", original)
    async with maker() as db:
        await db.execute(update(DeliveryAttempt).values(lease_until=utc_now_naive() - timedelta(seconds=1)))
        await db.commit()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(provider.calls) == 2  # DM channel confirmed, message accepted but receipt commit lost.
    assert (await state(fixture, receipt["delivery_id"]))[0].status == "uncertain"


@pytest.mark.parametrize("change", ["permission", "inactive", "owner", "scope", "destination"])
async def test_revalidates_manual_source_before_each_part(fixture, monkeypatch, change):
    maker, ids = fixture
    receipt = await queue(fixture, identity="member", kind="pm_briefing", scope="mine", content="x" * 2200)
    provider = Provider()
    async def send(request):
        response = provider(request)
        if len(provider.calls) == 1:
            async with maker() as db:
                if change == "permission":
                    await db.execute(update(UserPermission).where(UserPermission.user_id == ids["member"]).values(can_write=False))
                elif change == "inactive":
                    await db.execute(update(User).where(User.id == ids["member"]).values(is_active=False))
                elif change in ("owner", "scope"):
                    await db.execute(update(CommunicationRequest).where(CommunicationRequest.id == receipt["source_id"]).values(**({"owner_id": ids["admin"]} if change == "owner" else {"scope": "team"})))
                else:
                    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/456/changed")
                await db.commit()
        return response
    await svc.run_once(maker, transport=httpx.MockTransport(send))
    row, attempt = await state(fixture, receipt["delivery_id"])
    assert row.status == "cancelled" and len(provider.calls) == 1
    assert attempt.steps[0]["message_id"] == "101"


async def test_http_ownership_scopes_history_and_no_provider_before_worker(fixture, monkeypatch):
    no_http = AsyncMock(side_effect=AssertionError("no inline provider"))
    monkeypatch.setattr(svc, "send_step", no_http)
    async with client(fixture, "member") as member:
        for route in ("send", "send-daily-summary", "send-custom", "test-webhook", "send-weekly-report"):
            response = await member.post(f"/api/discord/{route}", json={"content": "forbidden"}, headers={"X-Agency-Send-Intent": "custom-v1"})
            assert response.status_code == 403
        assert (await member.post("/api/pm/briefing/discord", params={"scope": "team"})).status_code == 403
        response = await member.post("/api/pm/briefing/discord", json={"content": "Exact reviewed text", "date": "2026-09-16"})
        assert response.status_code == 202, response.text
        receipt = response.json()
        assert receipt["success"] is False and receipt["period_start"] == "2026-09-16"
        assert receipt["content"] == "Exact reviewed text"
        assert (await member.get("/api/deliveries/manual", params={"kind": "pm_briefing", "scope": "mine"})).json()[0]["delivery_id"] == receipt["delivery_id"]
        assert (await member.get("/api/deliveries/manual", params={"kind": "weekly_report"})).status_code == 403
    async with client(fixture) as admin:
        old = await admin.post("/api/discord/send-custom", json={"content": "Old digest"})
        assert old.status_code == 409
        response = await admin.post("/api/pm/briefing/discord", json={"content": "Admin private"})
        admin_receipt = response.json()
        assert (await admin.get("/api/deliveries/manual", params={"kind": "pm_briefing", "scope": "mine"})).json()[0]["delivery_id"] == admin_receipt["delivery_id"]
    async with client(fixture, "member") as member:
        assert (await member.get(f"/api/deliveries/{admin_receipt['delivery_id']}")).status_code == 403
        assert (await member.post(f"/api/deliveries/{admin_receipt['delivery_id']}/cancel")).status_code == 403
    no_http.assert_not_awaited()


async def test_summary_aliases_and_manual_endpoints_return_real_pending_receipts(fixture):
    async with client(fixture) as admin:
        first = await admin.post("/api/discord/send", params={"date": "2026-09-14"})
        second = await admin.post("/api/discord/send-daily-summary", params={"date": "2026-09-14"})
        assert first.status_code == second.status_code == 202
        assert first.json()["delivery_id"] == second.json()["delivery_id"]
        assert first.json()["ok"] is False and first.json()["success"] is False
        for route in ("send-custom", "test-webhook", "send-weekly-report"):
            response = await admin.post(f"/api/discord/{route}", json={"content": "Reviewed custom"}, headers={"X-Agency-Send-Intent": "custom-v1"})
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "pending"
            assert response.json()["success"] is False
        assert (await admin.post("/api/discord/send-weekly-report", params={"week_start": "2026-09-15"})).status_code == 422


async def test_pm_midnight_uses_business_day_and_scheduled_work(fixture, monkeypatch):
    from backend.services import insights
    from backend.services.temporal import business_zone
    maker, ids = fixture
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 17, 22, 30, tzinfo=timezone.utc).astimezone(tz or timezone.utc)
    monkeypatch.setattr(insights, "datetime", Clock)
    monkeypatch.setattr(settings, "AGENCY_TIMEZONE", "Europe/Madrid")
    async with maker() as db:
        db.add_all([
            Task(title="Planned tomorrow UTC", assigned_to=ids["member"], created_by=ids["member"], scheduled_date=date(2026, 9, 18), due_date=None),
            Task(title="Only deadline", assigned_to=ids["member"], created_by=ids["member"], due_date=datetime(2026, 9, 18)),
            Task(title="Overdue planned today", assigned_to=ids["member"], created_by=ids["member"], scheduled_date=date(2026, 9, 18), due_date=datetime(2026, 9, 17)),
            Task(title="Recurring template", assigned_to=ids["member"], created_by=ids["member"], scheduled_date=date(2026, 9, 18), is_recurring=True),
            Task(title="Other user", assigned_to=ids["admin"], created_by=ids["admin"], scheduled_date=date(2026, 9, 18)),
        ])
        await db.commit()
        result = await insights.get_daily_briefing(db, user_id=ids["member"], include_ai=False)
        assert result["date"] == "2026-09-18"
        assert {row["title"] for row in result["priorities"]} == {"Planned tomorrow UTC", "Only deadline"}
        assert [row["title"] for row in result["alerts"]] == ["Overdue planned today"]


async def test_schema_upgrade_adds_only_request_table_and_readiness_checks_key(fixture, engine):
    from backend.startup.delivery_schema import ensure_delivery_schema
    from backend.startup.readiness import check_database_ready
    from backend.db.models import CommunicationOccurrence, CommunicationSchedule
    async with engine.begin() as conn:
        # Reconstruct the real A schema, including absence of later B2 tables.
        await conn.run_sync(CommunicationOccurrence.__table__.drop)
        await conn.run_sync(CommunicationSchedule.__table__.drop)
        await conn.run_sync(CommunicationRequest.__table__.drop)
    await asyncio.gather(ensure_delivery_schema(engine), ensure_delivery_schema(engine))
    await check_database_ready(engine)
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX uq_communication_request_key"))
    with pytest.raises(RuntimeError):
        await check_database_ready(engine)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE UNIQUE INDEX uq_communication_request_key ON communication_requests(request_key)"))


async def test_connection_test_request_key_survives_lost_response_and_new_day(fixture, monkeypatch):
    maker, _ = fixture
    key = str(uuid4())
    async with client(fixture) as admin:
        first = (await admin.post("/api/discord/test-webhook", headers={"X-Agency-Request-Key": key})).json()
        provider = Provider()
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
        monkeypatch.setattr(discord, "business_today", lambda: date(2026, 9, 19))
        replay = (await admin.post("/api/discord/test-webhook", headers={"X-Agency-Request-Key": key})).json()
        assert replay["delivery_id"] == first["delivery_id"] and replay["status"] == "sent"
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
        assert len(provider.calls) == 1
        fresh = (await admin.post("/api/discord/test-webhook", headers={"X-Agency-Request-Key": str(uuid4())})).json()
        assert fresh["delivery_id"] != first["delivery_id"] and fresh["status"] == "pending"


async def test_dm_destination_rechecked_after_channel_confirmation(fixture, monkeypatch):
    maker, _ = fixture
    receipt = await queue(fixture, kind="weekly_report")
    provider = Provider()
    def send(request):
        response = provider(request)
        monkeypatch.setattr(settings, "DISCORD_OWNER_USER_ID", "987654321")
        return response
    await svc.run_once(maker, transport=httpx.MockTransport(send))
    row, attempt = await state(fixture, receipt["delivery_id"])
    assert len(provider.calls) == 1 and row.status == "cancelled"
    assert attempt.steps[0]["channel_id"] == "101"
    assert attempt.steps[1]["status"] == "pending"


async def test_explicit_key_rejects_changed_content_or_scope(fixture):
    maker, ids = fixture
    key = str(uuid4())
    async with maker() as db:
        user = await actor(db, ids["admin"])
        await manual.enqueue_request(db, user, **payload(kind="connection_test"), intent_key=key)
    for changes in ({"content": "Other text"}, {"scope": "mine"}):
        async with maker() as db:
            with pytest.raises(HTTPException) as err:
                await manual.enqueue_request(db, await actor(db, ids["admin"]), **(payload(kind="connection_test") | changes), intent_key=key)
            assert err.value.status_code == 409


async def test_identical_custom_after_success_reports_existing_receipt(fixture):
    maker, _ = fixture
    async with client(fixture) as admin:
        request = dict(json={"content": "Same deliberate text"}, headers={"X-Agency-Send-Intent": "custom-v1"})
        first = (await admin.post("/api/discord/send-custom", **request)).json()
        provider = Provider()
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
        again = (await admin.post("/api/discord/send-custom", **request)).json()
        assert again["delivery_id"] == first["delivery_id"]
        assert again["success"] is True and "sin enviar de nuevo" in again["message"]
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
        assert len(provider.calls) == 1
