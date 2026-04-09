"""Tests for forecast routes."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestForecastsList:
    async def test_list_forecasts_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/forecasts")
        assert resp.status_code == 200

    async def test_list_forecasts_filter_year(self, admin_client):
        resp = await admin_client.get("/api/finance/forecasts?year=2026")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestForecastGenerate:
    async def test_generate_returns_200(self, admin_client):
        resp = await admin_client.post("/api/finance/forecasts/generate")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestForecastRunway:
    async def test_runway_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/forecasts/runway")
        assert resp.status_code == 200
        data = resp.json()
        assert "cash" in data or "runway_months" in data or "message" in data


@pytest.mark.asyncio
class TestForecastVsActual:
    async def test_vs_actual_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/forecasts/vs-actual?year=2026")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestForecastCrud:
    async def test_create_forecast_422_missing_fields(self, admin_client):
        resp = await admin_client.post("/api/finance/forecasts", json={})
        assert resp.status_code == 422

    async def test_get_nonexistent_forecast_404(self, admin_client):
        resp = await admin_client.get("/api/finance/forecasts/99999")
        assert resp.status_code == 404
