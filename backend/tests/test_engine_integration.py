from __future__ import annotations

import httpx
import pytest

from backend.config import settings


@pytest.mark.asyncio
async def test_engine_projects_timeout_returns_504(admin_client, monkeypatch):
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.test")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    original_get = httpx.AsyncClient.get

    async def _timeout_get(self, url, *args, **kwargs):
        if isinstance(url, str) and url.startswith("https://engine.test"):
            raise httpx.TimeoutException("timeout")
        return await original_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _timeout_get)

    response = await admin_client.get("/api/engine/projects")
    assert response.status_code == 504
    assert response.json()["detail"] == "Engine request timed out"


@pytest.mark.asyncio
async def test_engine_metrics_request_error_returns_502(admin_client, monkeypatch):
    monkeypatch.setattr(settings, "ENGINE_API_URL", "https://engine.test")
    monkeypatch.setattr(settings, "ENGINE_SERVICE_KEY", "test-service-key")
    original_get = httpx.AsyncClient.get

    async def _request_error_get(self, url, *args, **kwargs):
        if isinstance(url, str) and url.startswith("https://engine.test"):
            request = httpx.Request("GET", "https://engine.test/api/integration/projects/1/metrics")
            raise httpx.RequestError("network error", request=request)
        return await original_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _request_error_get)

    response = await admin_client.get("/api/engine/projects/1/metrics")
    assert response.status_code == 502
    assert response.json()["detail"] == "Engine service unavailable"
