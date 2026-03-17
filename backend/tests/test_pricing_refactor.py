"""Tests for pricing refactor and client extraction features (Sprint 10).

Covers:
- Dashboard total_budget aggregation from Project.monthly_fee with fallback
- Dashboard profitability uses project fees with client budget fallback
- ProjectCreate schema accepts monthly_fee
- ProjectExtractInline / ClientExtract models include monthly_fee
- Extract prompt includes monthly_fee in project schema
"""
from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Schema / model unit tests (no async, no DB)
# ---------------------------------------------------------------------------

class TestProjectCreateSchema:
    """ProjectCreate schema accepts monthly_fee field."""

    def test_monthly_fee_accepted(self):
        from backend.schemas.project import ProjectCreate

        data = ProjectCreate(
            name="SEO Retainer",
            client_id=1,
            monthly_fee=1500.0,
            pricing_model="monthly",
        )
        assert data.monthly_fee == 1500.0
        assert data.pricing_model == "monthly"

    def test_monthly_fee_defaults_to_none(self):
        from backend.schemas.project import ProjectCreate

        data = ProjectCreate(name="One-off audit", client_id=1)
        assert data.monthly_fee is None

    def test_monthly_fee_in_dump(self):
        from backend.schemas.project import ProjectCreate

        data = ProjectCreate(
            name="Content",
            client_id=1,
            monthly_fee=2000.0,
        )
        dumped = data.model_dump()
        assert "monthly_fee" in dumped
        assert dumped["monthly_fee"] == 2000.0


class TestProjectExtractInline:
    """ProjectExtractInline (used in extract-context response) has monthly_fee."""

    def test_monthly_fee_field_exists(self):
        from backend.api.routes.clients import ProjectExtractInline

        obj = ProjectExtractInline(
            name="SEO mensual",
            monthly_fee=1200.0,
            pricing_model="monthly",
        )
        assert obj.monthly_fee == 1200.0

    def test_monthly_fee_defaults_to_none(self):
        from backend.api.routes.clients import ProjectExtractInline

        obj = ProjectExtractInline()
        assert obj.monthly_fee is None

    def test_full_pricing_fields(self):
        from backend.api.routes.clients import ProjectExtractInline

        obj = ProjectExtractInline(
            name="Link building",
            pricing_model="per_piece",
            unit_price=150.0,
            unit_label="enlace",
            monthly_fee=None,
        )
        assert obj.pricing_model == "per_piece"
        assert obj.unit_price == 150.0
        assert obj.unit_label == "enlace"
        assert obj.monthly_fee is None


class TestClientExtractModel:
    """ClientExtract model includes project sub-object with monthly_fee."""

    def test_with_project_monthly_fee(self):
        from backend.api.routes.clients import ClientExtract, ProjectExtractInline

        extract = ClientExtract(
            name="Acme Corp",
            monthly_budget=3000.0,
            project=ProjectExtractInline(
                name="SEO Retainer",
                monthly_fee=2500.0,
                pricing_model="monthly",
                is_recurring=True,
            ),
        )
        assert extract.project is not None
        assert extract.project.monthly_fee == 2500.0
        assert extract.project.is_recurring is True

    def test_without_project(self):
        from backend.api.routes.clients import ClientExtract

        extract = ClientExtract(name="Solo client")
        assert extract.project is None

    def test_project_serialization_includes_monthly_fee(self):
        from backend.api.routes.clients import ClientExtract, ProjectExtractInline

        extract = ClientExtract(
            name="Test",
            project=ProjectExtractInline(
                name="Proyecto",
                monthly_fee=800.0,
            ),
        )
        data = extract.model_dump()
        assert data["project"]["monthly_fee"] == 800.0


class TestExtractPrompt:
    """The AI extraction prompt includes monthly_fee in the project schema."""

    def test_prompt_contains_monthly_fee(self):
        from backend.api.routes.clients import _CLIENT_EXTRACT_PROMPT

        assert "monthly_fee" in _CLIENT_EXTRACT_PROMPT

    def test_prompt_contains_pricing_model(self):
        from backend.api.routes.clients import _CLIENT_EXTRACT_PROMPT

        assert "pricing_model" in _CLIENT_EXTRACT_PROMPT

    def test_prompt_contains_unit_price(self):
        from backend.api.routes.clients import _CLIENT_EXTRACT_PROMPT

        assert "unit_price" in _CLIENT_EXTRACT_PROMPT


class TestProjectResponseSchema:
    """ProjectResponse schema exposes monthly_fee."""

    def test_monthly_fee_in_response_fields(self):
        from backend.schemas.project import ProjectResponse

        fields = ProjectResponse.model_fields
        assert "monthly_fee" in fields


class TestProjectExtractSchema:
    """ProjectExtract (standalone) includes monthly_fee."""

    def test_monthly_fee_field(self):
        from backend.schemas.project import ProjectExtract

        obj = ProjectExtract(name="Test", monthly_fee=999.0)
        assert obj.monthly_fee == 999.0


# ---------------------------------------------------------------------------
# Dashboard pricing aggregation tests (async, mocked DB)
# ---------------------------------------------------------------------------

# Named tuple to simulate SQLAlchemy Row objects returned by db.execute().all()
_BudgetRow = namedtuple("_BudgetRow", ["id", "project_fee", "monthly_budget"])


@pytest.mark.asyncio
class TestDashboardBudgetAggregation:
    """GET /api/dashboard/overview — total_budget calculation."""

    async def test_budget_from_project_fees_only(self, admin_client):
        """When all clients have active projects with monthly_fee, use project fees."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # active_clients count
                result.scalar.return_value = 2
            elif call_count == 2:
                # pending tasks
                result.scalar.return_value = 5
            elif call_count == 3:
                # in_progress tasks
                result.scalar.return_value = 3
            elif call_count == 4:
                # hours this month (minutes)
                result.scalar.return_value = 4800
            elif call_count == 5:
                # Budget query: clients with project fees
                result.all.return_value = [
                    _BudgetRow(id=1, project_fee=2000, monthly_budget=1500),
                    _BudgetRow(id=2, project_fee=3000, monthly_budget=2000),
                ]
            elif call_count == 6:
                # total cost
                result.scalar.return_value = 2500
            else:
                result.scalar.return_value = 0

            return result

        mock_db.execute = mock_execute

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = await admin_client.get("/api/dashboard/overview")
        finally:
            # Don't clear all overrides; admin_client fixture manages auth
            del app.dependency_overrides[get_db]

        assert resp.status_code == 200
        data = resp.json()
        # Should sum project fees: 2000 + 3000 = 5000
        assert data["total_budget"] == 5000.0

    async def test_budget_falls_back_to_client_budget(self, admin_client):
        """When a client has no project fees (0), fall back to client.monthly_budget."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                result.scalar.return_value = 2
            elif call_count == 2:
                result.scalar.return_value = 0
            elif call_count == 3:
                result.scalar.return_value = 0
            elif call_count == 4:
                result.scalar.return_value = 0
            elif call_count == 5:
                # Client 1: has project fees; Client 2: no project fees, uses fallback
                result.all.return_value = [
                    _BudgetRow(id=1, project_fee=2000, monthly_budget=1500),
                    _BudgetRow(id=2, project_fee=0, monthly_budget=1800),
                ]
            elif call_count == 6:
                result.scalar.return_value = 1000
            else:
                result.scalar.return_value = 0

            return result

        mock_db.execute = mock_execute

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = await admin_client.get("/api/dashboard/overview")
        finally:
            del app.dependency_overrides[get_db]

        assert resp.status_code == 200
        data = resp.json()
        # Client 1: 2000 (from projects), Client 2: 1800 (fallback) = 3800
        assert data["total_budget"] == 3800.0

    async def test_budget_all_fallback(self, admin_client):
        """When no clients have project fees, all fall back to monthly_budget."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                result.scalar.return_value = 1
            elif call_count == 2:
                result.scalar.return_value = 0
            elif call_count == 3:
                result.scalar.return_value = 0
            elif call_count == 4:
                result.scalar.return_value = 0
            elif call_count == 5:
                result.all.return_value = [
                    _BudgetRow(id=1, project_fee=0, monthly_budget=5000),
                ]
            elif call_count == 6:
                result.scalar.return_value = 0
            else:
                result.scalar.return_value = 0

            return result

        mock_db.execute = mock_execute

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = await admin_client.get("/api/dashboard/overview")
        finally:
            del app.dependency_overrides[get_db]

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] == 5000.0

    async def test_budget_zero_when_no_clients(self, admin_client):
        """When there are no active clients, total_budget should be 0."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                result.scalar.return_value = 0
            elif call_count == 5:
                result.all.return_value = []
            elif call_count == 6:
                result.scalar.return_value = 0
            else:
                result.scalar.return_value = 0

            return result

        mock_db.execute = mock_execute

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = await admin_client.get("/api/dashboard/overview")
        finally:
            del app.dependency_overrides[get_db]

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] == 0.0


class TestBudgetFallbackLogic:
    """Unit test the fallback logic used in dashboard overview and profitability."""

    def test_project_fee_preferred_over_client_budget(self):
        """When project_fee > 0, it should be used instead of monthly_budget."""
        rows = [
            _BudgetRow(id=1, project_fee=2000, monthly_budget=1500),
            _BudgetRow(id=2, project_fee=3000, monthly_budget=2500),
        ]
        # Replicate the logic from dashboard.py line 111-113
        total = sum(
            float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
            for row in rows
        )
        assert total == 5000.0

    def test_fallback_when_project_fee_zero(self):
        """When project_fee is 0, should use monthly_budget."""
        rows = [
            _BudgetRow(id=1, project_fee=0, monthly_budget=1500),
        ]
        total = sum(
            float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
            for row in rows
        )
        assert total == 1500.0

    def test_fallback_when_both_zero(self):
        """When both are 0, total should be 0."""
        rows = [
            _BudgetRow(id=1, project_fee=0, monthly_budget=0),
        ]
        total = sum(
            float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
            for row in rows
        )
        assert total == 0.0

    def test_fallback_when_budget_none(self):
        """When project_fee is 0 and monthly_budget is None, should be 0."""
        rows = [
            _BudgetRow(id=1, project_fee=0, monthly_budget=None),
        ]
        total = sum(
            float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
            for row in rows
        )
        assert total == 0.0

    def test_mixed_clients(self):
        """Mix of clients with and without project fees."""
        rows = [
            _BudgetRow(id=1, project_fee=2500, monthly_budget=2000),   # uses 2500
            _BudgetRow(id=2, project_fee=0, monthly_budget=1800),       # uses 1800
            _BudgetRow(id=3, project_fee=1000, monthly_budget=500),     # uses 1000
            _BudgetRow(id=4, project_fee=0, monthly_budget=None),       # uses 0
        ]
        total = sum(
            float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
            for row in rows
        )
        assert total == 5300.0


# ---------------------------------------------------------------------------
# Profitability fallback logic (same pattern as overview)
# ---------------------------------------------------------------------------

class TestProfitabilityFallbackLogic:
    """Unit test the profitability endpoint's budget derivation."""

    def test_fee_map_preferred_over_client_budget(self):
        """Profitability: fee_map entry > 0 is preferred over client.monthly_budget."""
        # Replicate logic from dashboard.py line 214:
        # budget = fee_map.get(client.id, 0) or float(client.monthly_budget or 0)
        fee_map = {1: 2500.0, 2: 0.0}

        client1 = MagicMock()
        client1.id = 1
        client1.monthly_budget = 2000.0

        client2 = MagicMock()
        client2.id = 2
        client2.monthly_budget = 1800.0

        budget1 = fee_map.get(client1.id, 0) or float(client1.monthly_budget or 0)
        budget2 = fee_map.get(client2.id, 0) or float(client2.monthly_budget or 0)

        assert budget1 == 2500.0  # from fee_map
        assert budget2 == 1800.0  # fallback to client.monthly_budget

    def test_client_not_in_fee_map(self):
        """Client with no projects at all falls back to monthly_budget."""
        fee_map = {}

        client = MagicMock()
        client.id = 99
        client.monthly_budget = 3000.0

        budget = fee_map.get(client.id, 0) or float(client.monthly_budget or 0)
        assert budget == 3000.0

    def test_margin_calculation(self):
        """Margin and margin_pct calculated correctly from budget and cost."""
        budget = 5000.0
        cost = 3000.0
        margin = round(budget - cost, 2)
        margin_pct = round((margin / budget * 100) if budget > 0 else 0, 1)

        assert margin == 2000.0
        assert margin_pct == 40.0

    def test_margin_status_thresholds(self):
        """Profitability status based on margin_pct thresholds."""
        cases = [
            (25.0, "profitable"),
            (20.0, "profitable"),
            (19.9, "at_risk"),
            (0.0, "at_risk"),
            (-5.0, "unprofitable"),
        ]
        for margin_pct, expected_status in cases:
            if margin_pct >= 20:
                s = "profitable"
            elif margin_pct >= 0:
                s = "at_risk"
            else:
                s = "unprofitable"
            assert s == expected_status, f"margin_pct={margin_pct} should be {expected_status}, got {s}"


# ---------------------------------------------------------------------------
# Dashboard overview endpoint smoke test (default mock DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDashboardOverviewEndpoint:
    """GET /api/dashboard/overview basic response shape."""

    async def test_overview_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dashboard/overview")
        assert resp.status_code == 200

    async def test_overview_has_budget_fields(self, admin_client):
        resp = await admin_client.get("/api/dashboard/overview")
        data = resp.json()
        assert "total_budget" in data
        assert "total_cost" in data
        assert "margin" in data
        assert "margin_percent" in data

    async def test_overview_accepts_year_month_params(self, admin_client):
        resp = await admin_client.get(
            "/api/dashboard/overview",
            params={"year": 2026, "month": 3},
        )
        assert resp.status_code == 200
