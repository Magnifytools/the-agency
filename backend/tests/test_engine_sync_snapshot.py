from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest


def test_engine_snapshot_rejects_false_ids_bad_periods_and_incoherent_counts():
    from backend.services.engine_sync_service import _valid_snapshot

    summary = {
        "project_id": 99, "content_count": 10, "keyword_count": 11,
        "observed_keyword_count": 9, "keywords_top3": 2,
        "keywords_top10": 4, "keywords_top20": 7,
        "inspected_count": 10, "indexed_count": 8, "avg_position": 12.5,
        "clicks_30d": 13, "impressions_30d": 14, "as_of": "2026-09-20",
        "period_start": "2026-08-22", "previous_period_start": "2026-07-23",
        "ranking_device": "desktop",
    }
    alert = {
        "severity": "warning", "type": "traffic_drop", "title": "Valid",
        "detail": None, "detected_at": "2026-09-20T09:00:00+00:00",
    }
    alerts = {"project_id": 99, "alerts": [alert]}
    assert _valid_snapshot(summary, alerts, 99)
    nullable_date_alerts = {
        "project_id": 99,
        "alerts": [{**alert, "detected_at": None}],
    }
    assert _valid_snapshot(summary, nullable_date_alerts, 99)

    invalid_cases = []
    for key, value in (
        ("project_id", True),
        ("period_start", "2026-08-21"),
        ("as_of", "20-09-2026"),
        ("observed_keyword_count", 12),
        ("keywords_top10", 1),
        ("indexed_count", 11),
    ):
        candidate = deepcopy(summary)
        candidate[key] = value
        invalid_cases.append((candidate, alerts))
    invalid_cases.extend((summary, candidate) for candidate in (
        {"project_id": True, "alerts": []},
        {"project_id": 100, "alerts": []},
        {"project_id": 99, "alerts": ["not-an-alert"]},
        {"project_id": 99, "alerts": [{**alert, "severity": "unknown"}]},
        {"project_id": 99, "alerts": [{**alert, "type": ""}]},
        {"project_id": 99, "alerts": [{**alert, "title": None}]},
        {"project_id": 99, "alerts": [{**alert, "detail": 3}]},
        {"project_id": 99, "alerts": [{**alert, "detected_at": "not-a-date"}]},
    ))
    assert all(not _valid_snapshot(candidate, alert_data, 99) for candidate, alert_data in invalid_cases)


@pytest.mark.asyncio
async def test_engine_sync_replaces_only_a_complete_coherent_snapshot(monkeypatch):
    from backend.services import engine_sync_service as service

    client = SimpleNamespace(
        id=7, engine_project_id=99,
        engine_content_count=1, engine_keyword_count=2, engine_avg_position=3.0,
        engine_clicks_30d=4, engine_impressions_30d=5,
        engine_summary_data={"project_id": 99, "old": True},
        engine_alerts_data={"alerts": [{"title": "old"}]},
        engine_metrics_synced_at="old-time",
    )

    class Result:
        def all(self): return [(client.id, client.engine_project_id)]
    updates = []
    class Session:
        async def execute(self, statement):
            if statement.is_update:
                updates.append(statement.compile().params)
                return SimpleNamespace(rowcount=1)
            return Result()
        async def commit(self): return None
        async def rollback(self): return None
    @asynccontextmanager
    async def session_factory():
        yield Session()
    class Response:
        def __init__(self, payload): self.status_code, self.payload = 200, payload
        def json(self): return self.payload
    class Http:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def get(self, url, **_):
            if url.endswith('/summary'):
                return Response({"project_id": 99, "content_count": 10, "keyword_count": 11, "observed_keyword_count": 9, "keywords_top3": 2, "keywords_top10": 4, "keywords_top20": 7, "inspected_count": 10, "indexed_count": 8, "avg_position": 12.5, "clicks_30d": 13, "impressions_30d": 14, "as_of": "2026-09-20", "period_start": "2026-08-22", "previous_period_start": "2026-07-23", "ranking_device": "desktop"})
            return Response({"project_id": 99, "alerts": [{
                "severity": "warning", "type": "traffic_drop", "title": "New",
                "detail": None, "detected_at": "2026-09-20T09:00:00Z",
            }]})

    monkeypatch.setattr(service, "async_session", session_factory)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_: Http())
    monkeypatch.setattr(service.settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(service.settings, "ENGINE_SERVICE_KEY", "synthetic")

    assert await service.sync_engine_metrics() == {"synced": 1, "failed": 0}
    assert updates[0]["engine_content_count"] == 10
    assert updates[0]["engine_keyword_count"] == 11
    assert updates[0]["engine_summary_data"]["clicks_30d"] == 13
    assert updates[0]["engine_alerts_data"]["alerts"][0]["type"] == "traffic_drop"
    assert updates[0]["engine_metrics_synced_at"] is not None


@pytest.mark.asyncio
async def test_engine_sync_preserves_entire_snapshot_when_alerts_or_summary_is_invalid(monkeypatch):
    from backend.services import engine_sync_service as service

    client = SimpleNamespace(
        id=7, engine_project_id=99,
        engine_content_count=1, engine_keyword_count=2, engine_avg_position=3.0,
        engine_clicks_30d=4, engine_impressions_30d=5,
        engine_summary_data={"project_id": 99, "old": True},
        engine_alerts_data={"alerts": [{"title": "old"}]},
        engine_metrics_synced_at="old-time",
    )
    before = dict(client.__dict__)
    class Result:
        def all(self): return [(client.id, client.engine_project_id)]
    class Session:
        async def execute(self, statement):
            if statement.is_update:
                return SimpleNamespace(rowcount=1)
            return Result()
        async def commit(self): return None
        async def rollback(self): return None
    @asynccontextmanager
    async def session_factory(): yield Session()
    class Response:
        def __init__(self, status, payload): self.status_code, self.payload = status, payload
        def json(self): return self.payload
    class Http:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def get(self, url, **_):
            if url.endswith('/summary'):
                return Response(200, {"project_id": 99, "content_count": 10})
            return Response(200, {"alerts": []})
    monkeypatch.setattr(service, "async_session", session_factory)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_: Http())
    monkeypatch.setattr(service.settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(service.settings, "ENGINE_SERVICE_KEY", "synthetic")

    assert await service.sync_engine_metrics() == {"synced": 0, "failed": 1}
    assert client.__dict__ == before
