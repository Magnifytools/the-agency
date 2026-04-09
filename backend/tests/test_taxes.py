"""Tests for tax routes."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestTaxesList:
    async def test_list_taxes_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes")
        assert resp.status_code == 200

    async def test_list_taxes_filter_year(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes?year=2026")
        assert resp.status_code == 200

    async def test_list_taxes_filter_model(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes?model=303")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTaxCalendar:
    async def test_calendar_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes/calendar?year=2026")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTaxSummary:
    async def test_summary_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes/summary/2026")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTaxCalculate:
    async def test_calculate_returns_200(self, admin_client):
        resp = await admin_client.post("/api/finance/taxes/calculate/2026")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTaxCrud:
    async def test_create_tax_422_missing_fields(self, admin_client):
        resp = await admin_client.post("/api/finance/taxes", json={})
        assert resp.status_code == 422

    async def test_get_nonexistent_tax_404(self, admin_client):
        resp = await admin_client.get("/api/finance/taxes/99999")
        assert resp.status_code == 404
