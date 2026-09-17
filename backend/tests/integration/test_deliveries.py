"""Real transactions + simulated Discord: no external communications."""
import asyncio
from datetime import date, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.config import settings
from backend.db.models import Client, DailyUpdate, DailyUpdateStatus, Delivery, DeliveryAttempt, DiscordSettings, User, UserRole, UserPermission, WeeklyDigest
from backend.services import deliveries as svc
from backend.services.temporal import utc_now_naive


@pytest_asyncio.fixture
async def fixture(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/fake-test-token")
    async with maker() as db:
        actor = User(email=f"delivery-{uuid4()}@test.local", full_name="Delivery Test", hashed_password="unused", role=UserRole.admin, is_active=True)
        other = User(email=f"other-{uuid4()}@test.local", full_name="Other", hashed_password="unused", role=UserRole.member, is_active=True)
        client = Client(name="Delivery fixture")
        db.add_all([actor, other, client])
        await db.flush()
        daily = DailyUpdate(user_id=actor.id, date=date(2026, 9, 17), raw_text="Texto sin IA\n" + "x" * 2400)
        digest = WeeklyDigest(client_id=client.id, created_by=actor.id, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20), content={"greeting": "Hola", "date": "14–20", "sections": {"done": [], "need": [], "next": []}, "closing": "Fin"})
        db.add_all([daily, digest])
        await db.commit()
        ids = dict(actor=actor.id, other=other.id, daily=daily.id, digest=digest.id, client=client.id)
    yield maker, ids
    async with maker() as db:
        await db.execute(delete(DeliveryAttempt).where(DeliveryAttempt.delivery_id.in_(select(Delivery.id).where(Delivery.actor_id == ids["actor"]))))
        await db.execute(delete(Delivery).where(Delivery.actor_id == ids["actor"]))
        await db.execute(delete(DailyUpdate).where(DailyUpdate.id == ids["daily"]))
        await db.execute(delete(WeeklyDigest).where(WeeklyDigest.id == ids["digest"]))
        await db.execute(delete(UserPermission).where(UserPermission.user_id == ids["actor"]))
        await db.execute(delete(User).where(User.id.in_([ids["actor"], ids["other"]])))
        await db.execute(delete(Client).where(Client.id == ids["client"]))
        await db.commit()


async def enqueue(fixture, kind="daily", custom_content=None):
    maker, ids = fixture
    async with maker() as db:
        actor = await db.get(User, ids["actor"])
        row = await svc.enqueue(db, kind, ids[kind], actor, custom_content=custom_content)
        return row.id


async def state(fixture, delivery_id):
    maker, _ = fixture
    async with maker() as db:
        row = await db.get(Delivery, delivery_id)
        attempt = await svc.latest_attempt(db, delivery_id)
        return row, attempt


class Discord:
    def __init__(self, fail_at=None, status=403, timeout=False):
        self.calls = []
        self.fail_at, self.status, self.timeout = fail_at, status, timeout

    async def __call__(self, request):
        self.calls.append(request)
        if len(self.calls) == self.fail_at:
            if self.timeout:
                raise httpx.ReadTimeout("simulated lost reply", request=request)
            return httpx.Response(self.status, json={"retry_after": 2})
        return httpx.Response(200, json={"id": str(1000 + len(self.calls)), "channel_id": "456"})


async def test_concurrent_enqueue_and_workers_send_one_intent(fixture):
    maker, ids = fixture
    first, second = await asyncio.gather(enqueue(fixture), enqueue(fixture))
    assert first == second
    provider = Discord()
    await asyncio.gather(*(svc.run_once(maker, transport=httpx.MockTransport(provider)) for _ in range(2)))
    row, attempt = await state(fixture, first)
    assert row.status == "sent"
    assert len(provider.calls) == 2  # long raw text split, never truncated
    assert "Texto sin IA" in row.payload["text"] and row.payload["text"].endswith("x" * 2400)
    assert all(s["message_id"] for s in attempt.steps)
    async with maker() as db:
        assert (await db.get(DailyUpdate, ids["daily"])).status == DailyUpdateStatus.sent


async def test_enqueue_commit_failure_does_not_leave_intent(fixture, monkeypatch):
    maker, ids = fixture
    async with maker() as db:
        actor = await db.get(User, ids["actor"])
        monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
        with pytest.raises(RuntimeError):
            await svc.enqueue(db, "daily", ids["daily"], actor)
    async with maker() as db:
        assert await db.scalar(select(Delivery.id).where(Delivery.source_id == ids["daily"], Delivery.source_kind == "daily")) is None
        assert (await db.get(DailyUpdate, ids["daily"])).raw_text.startswith("Texto sin IA")


async def test_partial_rejection_retry_preserves_confirmed_steps(fixture):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    provider = Discord(fail_at=2)
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, attempt = await state(fixture, delivery_id)
    assert row.status == "failed" and [s["status"] for s in attempt.steps] == ["sent", "failed"]
    async with maker() as db:
        row = await db.get(Delivery, delivery_id)
        source = await db.get(DailyUpdate, ids["daily"])
        assert source.status == DailyUpdateStatus.draft
        await svc.retry(db, row, source)
    retry_provider = Discord()
    await svc.run_once(maker, transport=httpx.MockTransport(retry_provider))
    assert len(retry_provider.calls) == 1
    row, attempt = await state(fixture, delivery_id)
    assert row.status == "sent" and attempt.number == 2
    assert attempt.steps[0]["message_id"] == "1001"


async def test_timeout_uncertain_never_retries_and_explicit_resend_is_idempotent(fixture):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    provider = Discord(fail_at=1, timeout=True)
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    for _ in range(2):
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(provider.calls) == 1
    row, _ = await state(fixture, delivery_id)
    assert row.status == "uncertain"
    async with maker() as db:
        row = await db.get(Delivery, delivery_id)
        source = await db.get(DailyUpdate, ids["daily"])
        actor = await db.get(User, ids["actor"])
        with pytest.raises(svc.HTTPException):
            await svc.retry(db, row, source)
        first = await svc.resend(db, row, source, actor, "review-key-123456789")
        second = await svc.resend(db, row, source, actor, "review-key-123456789")
        assert first.id == second.id and first.id != row.id
        assert first.resend_of == row.id


async def test_accepted_then_receipt_commit_fails_recovers_uncertain(fixture, monkeypatch):
    maker, _ = fixture
    delivery_id = await enqueue(fixture)
    provider = Discord()
    from sqlalchemy.ext.asyncio import AsyncSession
    original = AsyncSession.commit
    async def fail_receipt(db):
        if provider.calls:
            raise RuntimeError("DB down after provider accepted")
        await original(db)
    monkeypatch.setattr(AsyncSession, "commit", fail_receipt)
    with pytest.raises(RuntimeError):
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
    monkeypatch.setattr(AsyncSession, "commit", original)
    async with maker() as db:
        await db.execute(update(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id).values(lease_until=utc_now_naive() - timedelta(seconds=1)))
        await db.commit()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, _ = await state(fixture, delivery_id)
    assert row.status == "uncertain" and len(provider.calls) == 1


@pytest.mark.parametrize("change", ["source", "actor", "destination", "delete"])
async def test_preflight_cancels_changed_source_or_permissions_without_http(fixture, monkeypatch, change):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    async with maker() as db:
        if change == "source":
            (await db.get(DailyUpdate, ids["daily"])).raw_text = "Nueva versión"
        elif change == "actor":
            (await db.get(User, ids["actor"])).is_active = False
        elif change == "delete":
            await db.execute(delete(DailyUpdate).where(DailyUpdate.id == ids["daily"]))
        else:
            monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/789/other-test-token")
        await db.commit()
    provider = Discord()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, _ = await state(fixture, delivery_id)
    assert row.status == "cancelled" and provider.calls == []


async def test_edit_during_external_send_preserves_new_draft(fixture):
    maker, ids = fixture
    # One part: edit occurs while the provider is accepting the only message.
    async with maker() as db:
        (await db.get(DailyUpdate, ids["daily"])).raw_text = "Original"
        await db.commit()
    delivery_id = await enqueue(fixture)
    async def provider(request):
        async with maker() as db:
            daily = await db.get(DailyUpdate, ids["daily"])
            daily.raw_text = "Borrador nuevo durante el envío"
            await db.commit()
        return httpx.Response(200, json={"id": "123", "channel_id": "456"})
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, _ = await state(fixture, delivery_id)
    assert row.status == "sent" and "Original" in row.payload["text"]
    async with maker() as db:
        source = await db.get(DailyUpdate, ids["daily"])
        assert source.status == DailyUpdateStatus.draft
        assert (await svc.receipt(db, row, source))["source_changed"] is True


async def test_thread_partial_failure_is_not_success_and_retry_skips_header(fixture):
    maker, _ = fixture
    async with maker() as db:
        ds = DiscordSettings(bot_token="test-bot", webhook_url="https://discord.com/api/webhooks/123/fake-test-token")
        db.add(ds)
        await db.commit()
        ds_id = ds.id
    try:
        delivery_id = await enqueue(fixture)
        provider = Discord(fail_at=2)
        await svc.run_once(maker, transport=httpx.MockTransport(provider))
        row, attempt = await state(fixture, delivery_id)
        assert row.status == "failed"
        assert [s["status"] for s in attempt.steps] == ["sent", "failed", "pending", "pending"]
        async with maker() as db:
            await svc.retry(db, await db.get(Delivery, delivery_id), await db.get(DailyUpdate, row.source_id))
        retry_provider = Discord()
        await svc.run_once(maker, transport=httpx.MockTransport(retry_provider))
        assert str(retry_provider.calls[0].url).endswith("/messages/1001/threads")
        assert len(retry_provider.calls) == 3
        assert (await state(fixture, delivery_id))[0].status == "sent"
    finally:
        async with maker() as db:
            await db.execute(delete(DiscordSettings).where(DiscordSettings.id == ds_id))
            await db.commit()


async def test_digest_ownership_permission_revoke_and_snapshot(fixture):
    maker, ids = fixture
    async with maker() as db:
        actor = await db.get(User, ids["actor"])
        actor.role = UserRole.member
        db.add(UserPermission(user_id=actor.id, module="digests", can_read=True, can_write=True))
        digest = await db.get(WeeklyDigest, ids["digest"])
        digest.created_by = ids["other"]
        await db.commit()
    with pytest.raises(svc.HTTPException) as err:
        await enqueue(fixture, "digest")
    assert err.value.status_code == 403
    async with maker() as db:
        (await db.get(WeeklyDigest, ids["digest"])).created_by = ids["actor"]
        await db.commit()
    delivery_id = await enqueue(fixture, "digest", custom_content="Texto revisado específicamente")
    row, _ = await state(fixture, delivery_id)
    assert row.payload["text"] == "Texto revisado específicamente"
    async with maker() as db:
        await db.execute(update(UserPermission).where(UserPermission.user_id == ids["actor"]).values(can_write=False))
        await db.commit()
    provider = Discord()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert (await state(fixture, delivery_id))[0].status == "cancelled"
    assert not provider.calls


async def test_structured_daily_keeps_long_content_and_unicode(fixture):
    maker, ids = fixture
    full_text = "📚" * 2200 + " final conservado"
    async with maker() as db:
        (await db.get(DailyUpdate, ids["daily"])).parsed_data = {"projects": [], "general": [{"description": full_text}], "tomorrow": []}
        await db.commit()
    delivery_id = await enqueue(fixture)
    row, _ = await state(fixture, delivery_id)
    assert full_text in row.payload["text"]
    chunks = row.payload["steps"]
    assert "".join(s["content"] for s in chunks) == row.payload["text"]
    assert all(len(s["content"].encode("utf-16-le")) // 2 <= 1900 for s in chunks)


async def test_provider_request_logs_do_not_expose_webhook_token(fixture, caplog):
    import logging
    maker, _ = fixture
    await enqueue(fixture)
    caplog.set_level(logging.INFO, logger="httpx")
    await svc.run_once(maker, transport=httpx.MockTransport(Discord()))
    assert "[redacted]" in caplog.text
    assert "fake-test-token" not in caplog.text


async def test_actor_revoked_after_claim_prevents_external_call(fixture):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    async with maker() as db:
        claimed = await svc.claim(db)
    async with maker() as db:
        (await db.get(User, ids["actor"])).is_active = False
        await db.commit()
    provider = Discord()
    await svc.dispatch_claim(maker, claimed, transport=httpx.MockTransport(provider))
    assert (await state(fixture, delivery_id))[0].status == "cancelled"
    assert not provider.calls


async def test_fence_reloads_precached_identity_before_any_external_effect(fixture):
    maker, _ = fixture
    delivery_id = await enqueue(fixture)
    async with maker() as db:
        claimed = await svc.claim(db)
    async with maker() as stale:
        cached = await stale.get(Delivery, delivery_id)
        cached_attempt = await svc.latest_attempt(stale, delivery_id)
        assert cached.status == "sending"
        async with maker() as db:
            (await db.get(Delivery, delivery_id)).status = "uncertain"
            current_attempt = await svc.latest_attempt(db, delivery_id)
            current_attempt.status = "uncertain"
            current_attempt.lease_until = utc_now_naive() - timedelta(seconds=1)
            await db.commit()
        row, attempt = await svc._locked_attempt(stale, delivery_id, claimed[1])
        assert row is None and attempt is None
        assert cached.status == "uncertain"
        assert cached_attempt.status == "uncertain"
    provider = Discord()
    await svc.dispatch_claim(maker, claimed, transport=httpx.MockTransport(provider))
    assert provider.calls == []


async def test_slow_marker_commit_does_not_send_after_lease_expires(fixture, monkeypatch):
    maker, _ = fixture
    await enqueue(fixture)
    from sqlalchemy.ext.asyncio import AsyncSession
    original_commit = AsyncSession.commit
    now = utc_now_naive()
    monkeypatch.setattr(svc, "utc_now_naive", lambda: now)
    async def delayed_commit(db):
        nonlocal now
        starts_http = any(isinstance(item, DeliveryAttempt) and any(step["status"] == "sending" for step in item.steps) for item in db.dirty)
        await original_commit(db)
        if starts_http:
            now += timedelta(seconds=svc.LEASE_SECONDS + 1)
    monkeypatch.setattr(AsyncSession, "commit", delayed_commit)
    provider = Discord()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert provider.calls == []


async def test_schema_upgrade_from_previous_schema_is_pure(engine):
    from backend.startup.delivery_schema import ensure_delivery_schema
    from backend.startup.readiness import check_database_ready
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE delivery_attempts"))
        await conn.execute(text("DROP TABLE deliveries"))
    with pytest.raises(Exception):
        await check_database_ready(engine)
    await asyncio.gather(ensure_delivery_schema(engine), ensure_delivery_schema(engine))
    await check_database_ready(engine)


async def test_http_202_receipt_and_resend_requires_review(admin_client, db_session, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/fake-test-token")
    daily = DailyUpdate(user_id=admin_user.id, date=date(2026, 9, 17), raw_text="Sin parsear")
    db_session.add(daily)
    await db_session.commit()
    queued = await admin_client.post(f"/api/dailys/{daily.id}/send-discord")
    assert queued.status_code == 202, queued.text
    data = queued.json()
    assert data["status"] == "pending" and data["success"] is False
    assert "Sin parsear" in data["content"]
    fetched = await admin_client.get(f"/api/deliveries/{data['delivery_id']}")
    assert fetched.status_code == 200 and fetched.json()["steps"][0]["status"] == "pending"
    missing_review = await admin_client.post(f"/api/deliveries/{data['delivery_id']}/resend", json={"review_key": "long-enough-review-key", "reviewed": False})
    assert missing_review.status_code == 422


async def test_rate_limit_retry_waits_without_reposting_early(fixture):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    provider = Discord(fail_at=1, status=429)
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    async with maker() as db:
        row = await db.get(Delivery, delivery_id)
        assert row.error_code == "rate_limit"
        await svc.retry(db, row, await db.get(DailyUpdate, ids["daily"]))
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert len(provider.calls) == 1


async def test_late_response_cannot_overwrite_uncertain_attempt(fixture):
    maker, _ = fixture
    delivery_id = await enqueue(fixture)
    async def provider(request):
        async with maker() as db:
            await db.execute(update(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id).values(lease_until=utc_now_naive() - timedelta(seconds=1)))
            await db.commit()
            await svc.recover_expired(db)
        return httpx.Response(200, json={"id": "123", "channel_id": "456"})
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    row, attempt = await state(fixture, delivery_id)
    assert row.status == "uncertain" and attempt.status == "uncertain"
    assert attempt.steps[0]["status"] == "sent" and attempt.steps[0]["message_id"] == "123"


async def test_expired_pending_is_not_sent_but_explicit_enqueue_can_renew(fixture):
    maker, _ = fixture
    delivery_id = await enqueue(fixture)
    async with maker() as db:
        (await db.get(Delivery, delivery_id)).expires_at = utc_now_naive() - timedelta(days=1)
        await db.commit()
    provider = Discord()
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    assert (await state(fixture, delivery_id))[0].status == "expired"
    assert provider.calls == []
    assert await enqueue(fixture) == delivery_id
    assert (await state(fixture, delivery_id))[0].status == "pending"


async def test_uncertain_resend_preserves_reviewed_old_text_after_source_edit(fixture):
    maker, ids = fixture
    delivery_id = await enqueue(fixture)
    provider = Discord(fail_at=1, timeout=True)
    await svc.run_once(maker, transport=httpx.MockTransport(provider))
    async with maker() as db:
        row = await db.get(Delivery, delivery_id)
        source = await db.get(DailyUpdate, ids["daily"])
        source.raw_text = "Nueva versión que no se debe reemplazar"
        actor = await db.get(User, ids["actor"])
        replacement = await svc.resend(db, row, source, actor, "review-old-version-123456")
        replacement_id = replacement.id
    await svc.run_once(maker, transport=httpx.MockTransport(Discord()))
    assert (await state(fixture, replacement_id))[0].status == "sent"
    async with maker() as db:
        source = await db.get(DailyUpdate, ids["daily"])
        assert source.raw_text.startswith("Nueva versión") and source.status == DailyUpdateStatus.draft


async def test_http_digest_source_and_receipt_are_owner_scoped(member_client, member_user, admin_user, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/fake-test-token")
    client = Client(name="Scoped fixture")
    db_session.add(client)
    db_session.add(UserPermission(user_id=member_user.id, module="digests", can_read=True, can_write=True))
    await db_session.flush()
    digest = WeeklyDigest(client_id=client.id, created_by=admin_user.id, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20), content={"sections": {"done": [], "need": [], "next": []}})
    db_session.add(digest)
    await db_session.commit()
    await db_session.refresh(member_user, ["permissions"])
    sent = await member_client.post(f"/api/discord/send-digest/{digest.id}", json={"content": "attempt"})
    assert sent.status_code == 403
    row = await svc.enqueue(db_session, "digest", digest.id, admin_user, custom_content="Only owner/admin")
    assert (await member_client.get(f"/api/deliveries/{row.id}")).status_code == 403
    assert (await member_client.get(f"/api/deliveries?source_kind=digest&source_id={digest.id}")).status_code == 403
    assert (await member_client.post(f"/api/deliveries/{row.id}/cancel")).status_code == 403
