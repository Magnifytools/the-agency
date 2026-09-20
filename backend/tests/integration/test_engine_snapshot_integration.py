from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.config import settings
from backend.db.models import Client, ClientStatus

pytestmark = pytest.mark.integration


_CACHE_FIELDS = (
    "engine_content_count",
    "engine_keyword_count",
    "engine_avg_position",
    "engine_clicks_30d",
    "engine_impressions_30d",
    "engine_metrics_synced_at",
    "engine_summary_data",
    "engine_alerts_data",
)


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _ProxyHTTP:
    calls: list[tuple[str, dict | None]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, *, headers=None, params=None):
        self.calls.append((url, params))
        if url.endswith("/projects"):
            return _Response([{"id": 81, "name": "Engine project"}])
        if url.endswith("/metrics"):
            return _Response({"project_id": 81, "clicks_30d": 14})
        return _Response({"project_id": 81, "sections": []})


def _seed_client(name: str, project_id: int | None = 81) -> Client:
    return Client(
        name=name,
        status=ClientStatus.active,
        engine_project_id=project_id,
        engine_content_count=8,
        engine_keyword_count=13,
        engine_avg_position=4.5,
        engine_clicks_30d=21,
        engine_impressions_30d=144,
        engine_metrics_synced_at=datetime.now(timezone.utc),
        engine_summary_data={"old": "summary"},
        engine_alerts_data={"alerts": [{"old": True}]},
    )


def _assert_cache_cleared(client: Client) -> None:
    assert {field: getattr(client, field) for field in _CACHE_FIELDS} == {
        field: None for field in _CACHE_FIELDS
    }


@pytest.mark.asyncio
async def test_engine_proxies_are_admin_only_and_forward_valid_payloads(
    admin_client, member_client, monkeypatch
):
    from backend.api.routes import engine_integration

    _ProxyHTTP.calls = []
    monkeypatch.setattr(engine_integration.httpx, "AsyncClient", _ProxyHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")

    paths = (
        "/api/engine/projects",
        "/api/engine/projects/81/metrics",
        "/api/engine/projects/81/report-data?from_date=2026-08-01&to_date=2026-08-31",
    )
    for path in paths:
        assert (await member_client.get(path)).status_code == 403
    assert _ProxyHTTP.calls == []

    responses = [await admin_client.get(path) for path in paths]
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert responses[0].json() == [{"id": 81, "name": "Engine project"}]
    assert responses[1].json()["clicks_30d"] == 14
    assert responses[2].json()["sections"] == []
    assert _ProxyHTTP.calls[-1][1] == {
        "from_date": "2026-08-01",
        "to_date": "2026-08-31",
    }


@pytest.mark.asyncio
async def test_only_admin_can_change_engine_link_and_relink_or_unlink_clears_snapshot(
    admin_client, make_member_client, db_session, monkeypatch
):
    from backend.api.routes import engine_integration

    async def valid_target(_project_id):
        return None

    monkeypatch.setattr(engine_integration, "validate_link_target", valid_target)
    client = _seed_client("Relink snapshot")
    db_session.add(client)
    await db_session.flush()

    member = await make_member_client([("clients", True, True)])
    try:
        denied = await member.put(
            f"/api/clients/{client.id}", json={"engine_project_id": 82}
        )
        assert denied.status_code == 403
        assert client.engine_project_id == 81
    finally:
        await member.aclose()

    relinked = await admin_client.put(
        f"/api/clients/{client.id}", json={"engine_project_id": 82}
    )
    assert relinked.status_code == 200, relinked.text
    await db_session.refresh(client)
    assert client.engine_project_id == 82
    _assert_cache_cleared(client)

    for field, value in {
        "engine_content_count": 2,
        "engine_keyword_count": 3,
        "engine_avg_position": 5.0,
        "engine_clicks_30d": 7,
        "engine_impressions_30d": 11,
        "engine_metrics_synced_at": datetime.now(timezone.utc),
        "engine_summary_data": {"fresh": True},
        "engine_alerts_data": {"alerts": []},
    }.items():
        setattr(client, field, value)
    await db_session.flush()

    unlinked = await admin_client.put(
        f"/api/clients/{client.id}", json={"engine_project_id": None}
    )
    assert unlinked.status_code == 200, unlinked.text
    await db_session.refresh(client)
    assert client.engine_project_id is None
    _assert_cache_cleared(client)


@pytest.mark.asyncio
async def test_engine_link_validation_happens_before_client_row_lock(
    engine, admin_user, monkeypatch
):
    from backend.api.deps import get_current_user
    from backend.api.routes import engine_integration
    from backend.db.database import get_db
    from backend.main import app

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as setup:
        client = _seed_client("Link validation lock")
        setup.add(client)
        await setup.commit()
        client_id = client.id

    validation_started = asyncio.Event()
    release_validation = asyncio.Event()

    async def held_validation(project_id):
        assert project_id == 82
        validation_started.set()
        await release_validation.wait()

    async def independent_db():
        async with session_factory() as session:
            yield session

    original_db = app.dependency_overrides.get(get_db)
    original_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = independent_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    monkeypatch.setattr(engine_integration, "validate_link_target", held_validation)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            request = asyncio.create_task(http.put(
                f"/api/clients/{client_id}", json={"engine_project_id": 82}
            ))
            await asyncio.wait_for(validation_started.wait(), timeout=2)
            async with session_factory() as concurrent:
                locked = (await concurrent.execute(
                    select(Client).where(Client.id == client_id).with_for_update()
                )).scalar_one()
                locked.name = "Changed while Engine validates"
                await asyncio.wait_for(concurrent.commit(), timeout=1)
            release_validation.set()
            response = await asyncio.wait_for(request, timeout=2)
        assert response.status_code == 200, response.text
        async with session_factory() as verify:
            current = await verify.get(Client, client_id)
            assert current.name == "Changed while Engine validates"
            assert current.engine_project_id == 82
            _assert_cache_cleared(current)
    finally:
        release_validation.set()
        if original_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_db
        if original_user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = original_user
        async with session_factory() as cleanup:
            stale = await cleanup.get(Client, client_id)
            if stale is not None:
                await cleanup.delete(stale)
                await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(("upstream_status", "projects", "expected_status"), [
    (200, [], 422),
    (503, [], 502),
])
async def test_invalid_or_failed_engine_lookup_does_not_change_client(
    admin_client, db_session, monkeypatch, upstream_status, projects, expected_status
):
    from backend.api.routes import engine_integration

    class LookupHTTP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return _Response(projects, upstream_status)

    monkeypatch.setattr(engine_integration.httpx, "AsyncClient", LookupHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    client = _seed_client(f"Rejected link {expected_status}")
    db_session.add(client)
    await db_session.flush()
    before = {field: getattr(client, field) for field in _CACHE_FIELDS}

    response = await admin_client.put(
        f"/api/clients/{client.id}", json={"engine_project_id": 999}
    )
    assert response.status_code == expected_status, response.text
    await db_session.refresh(client)
    assert client.engine_project_id == 81
    assert {field: getattr(client, field) for field in _CACHE_FIELDS} == before


@pytest.mark.asyncio
async def test_malformed_engine_lookup_is_502_and_does_not_change_client(
    admin_client, db_session, monkeypatch
):
    from backend.api.routes import engine_integration

    class MalformedResponse:
        status_code = 200

        def json(self):
            raise ValueError("malformed JSON with private upstream details")

    class LookupHTTP:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return MalformedResponse()

    monkeypatch.setattr(engine_integration.httpx, "AsyncClient", LookupHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    client = _seed_client("Malformed link response")
    db_session.add(client)
    await db_session.flush()
    before = {field: getattr(client, field) for field in _CACHE_FIELDS}

    response = await admin_client.put(
        f"/api/clients/{client.id}", json={"engine_project_id": 999}
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Invalid Engine response"}
    assert "private upstream details" not in response.text
    await db_session.refresh(client)
    assert client.engine_project_id == 81
    assert {field: getattr(client, field) for field in _CACHE_FIELDS} == before

class _HeldSnapshotHTTP:
    started: asyncio.Event
    release: asyncio.Event

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, *, headers=None):
        if url.endswith("/summary"):
            self.started.set()
            await self.release.wait()
            return _Response({
                "project_id": 81,
                "content_count": 89,
                "keyword_count": 55,
                "observed_keyword_count": 50,
                "keywords_top3": 8,
                "keywords_top10": 19,
                "keywords_top20": 31,
                "inspected_count": 40,
                "indexed_count": 35,
                "avg_position": 3.2,
                "clicks_30d": 233,
                "impressions_30d": 1597,
                "as_of": "2026-09-20",
                "period_start": "2026-08-22",
                "previous_period_start": "2026-07-23",
                "ranking_device": "desktop",
            })
        return _Response({"project_id": 81, "alerts": [{
            "severity": "warning", "type": "traffic_drop", "title": "Drop",
            "detail": None, "detected_at": "2026-09-20T09:00:00Z",
        }]})


class _CompleteSnapshotHTTP:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, *, headers=None):
        if url.endswith("/summary"):
            return _Response({
                "project_id": 81,
                "content_count": 34,
                "keyword_count": 21,
                "observed_keyword_count": 18,
                "keywords_top3": 3,
                "keywords_top10": 7,
                "keywords_top20": 12,
                "inspected_count": 20,
                "indexed_count": 15,
                "avg_position": 7.4,
                "clicks_30d": 55,
                "impressions_30d": 377,
                "as_of": "2026-09-20",
                "period_start": "2026-08-22",
                "previous_period_start": "2026-07-23",
                "ranking_device": "desktop",
            })
        return _Response({"project_id": 81, "alerts": [{
            "severity": "warning", "type": "drop", "title": "Drop",
            "detail": None, "detected_at": "2026-09-20T09:00:00Z",
        }]})


class _InvalidSnapshotHTTP(_CompleteSnapshotHTTP):
    mode: str

    async def get(self, url, *, headers=None):
        response = await super().get(url, headers=headers)
        payload = response.json()
        if self.mode == "summary" and url.endswith("/summary"):
            payload["period_start"] = "2026-08-21"
        if self.mode == "alerts" and url.endswith("/alerts"):
            payload["project_id"] = 82
        return _Response(payload)


@pytest.mark.asyncio
async def test_sync_success_persists_one_complete_snapshot_in_postgres(
    engine, monkeypatch
):
    from backend.services import engine_sync_service

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def madrid_session_factory():
        async with session_factory() as session:
            await session.execute(text("SET TIME ZONE 'Europe/Madrid'"))
            yield session

    fixed_utc = datetime(2026, 9, 20, 18, 59, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return fixed_utc

    async with session_factory() as setup:
        client = _seed_client("Successful PG snapshot")
        setup.add(client)
        await setup.commit()
        client_id = client.id

    monkeypatch.setattr(engine_sync_service, "async_session", madrid_session_factory)
    monkeypatch.setattr(engine_sync_service, "datetime", FixedDateTime)
    monkeypatch.setattr(engine_sync_service.httpx, "AsyncClient", _CompleteSnapshotHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    try:
        assert await engine_sync_service.sync_engine_metrics() == {"synced": 1, "failed": 0}
        async with session_factory() as verify:
            current = await verify.get(Client, client_id)
            assert current.engine_content_count == 34
            assert current.engine_keyword_count == 21
            assert current.engine_clicks_30d == 55
            assert current.engine_impressions_30d == 377
            assert current.engine_summary_data["project_id"] == 81
            assert current.engine_alerts_data == {
                "project_id": 81,
                "alerts": [{
                    "severity": "warning", "type": "drop", "title": "Drop",
                    "detail": None, "detected_at": "2026-09-20T09:00:00Z",
                }],
            }
            assert current.engine_metrics_synced_at == fixed_utc
    finally:
        async with session_factory() as cleanup:
            stale = await cleanup.get(Client, client_id)
            if stale is not None:
                await cleanup.delete(stale)
                await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_component", ["summary", "alerts"])
async def test_failed_component_preserves_the_entire_previous_snapshot(
    engine, monkeypatch, invalid_component
):
    from backend.services import engine_sync_service

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as setup:
        client = _seed_client(f"Preserved failed {invalid_component}")
        setup.add(client)
        await setup.commit()
        client_id = client.id
        before = {field: getattr(client, field) for field in _CACHE_FIELDS}

    _InvalidSnapshotHTTP.mode = invalid_component
    monkeypatch.setattr(engine_sync_service, "async_session", session_factory)
    monkeypatch.setattr(engine_sync_service.httpx, "AsyncClient", _InvalidSnapshotHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    try:
        assert await engine_sync_service.sync_engine_metrics() == {"synced": 0, "failed": 1}
        async with session_factory() as verify:
            current = await verify.get(Client, client_id)
            assert {field: getattr(current, field) for field in _CACHE_FIELDS} == before
    finally:
        async with session_factory() as cleanup:
            stale = await cleanup.get(Client, client_id)
            if stale is not None:
                await cleanup.delete(stale)
                await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_project", "expected_status"),
    [
        ({"engine_project_id": 82}, 82, ClientStatus.active),
        ({"status": "paused"}, 81, ClientStatus.paused),
    ],
)
async def test_sync_cas_does_not_write_snapshot_after_relink_or_deactivation(
    engine, admin_user, monkeypatch, mutation, expected_project, expected_status
):
    from backend.api.deps import get_current_user
    from backend.api.routes import engine_integration
    from backend.db.database import get_db
    from backend.main import app
    from backend.services import engine_sync_service

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as setup:
        client = _seed_client(f"CAS {expected_status.value} {expected_project}")
        setup.add(client)
        await setup.commit()
        client_id = client.id

    async def independent_db():
        async with session_factory() as session:
            yield session

    original_db = app.dependency_overrides.get(get_db)
    original_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = independent_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    monkeypatch.setattr(engine_sync_service, "async_session", session_factory)
    monkeypatch.setattr(engine_sync_service.httpx, "AsyncClient", _HeldSnapshotHTTP)
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    _HeldSnapshotHTTP.started = asyncio.Event()
    _HeldSnapshotHTTP.release = asyncio.Event()

    async def valid_target(_project_id):
        return None

    monkeypatch.setattr(engine_integration, "validate_link_target", valid_target)

    try:
        sync_task = asyncio.create_task(engine_sync_service.sync_engine_metrics())
        await asyncio.wait_for(_HeldSnapshotHTTP.started.wait(), timeout=2)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as mutator:
            response = await mutator.put(f"/api/clients/{client_id}", json=mutation)
        assert response.status_code == 200, response.text
        _HeldSnapshotHTTP.release.set()
        assert await asyncio.wait_for(sync_task, timeout=2) == {"synced": 0, "failed": 1}

        async with session_factory() as verify:
            current = await verify.get(Client, client_id)
            assert current is not None
            assert current.engine_project_id == expected_project
            assert current.status == expected_status
            assert current.engine_content_count != 89
            assert current.engine_clicks_30d != 233
            if "engine_project_id" in mutation:
                _assert_cache_cleared(current)
    finally:
        _HeldSnapshotHTTP.release.set()
        if original_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_db
        if original_user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = original_user
        async with session_factory() as cleanup:
            stale = await cleanup.get(Client, client_id)
            if stale is not None:
                await cleanup.delete(stale)
                await cleanup.commit()
