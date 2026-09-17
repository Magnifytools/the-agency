"""Health must represent measured evidence, not missing instrumentation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.clients import _health_capabilities
from backend.db.models import TaskStatus, UserRole
from backend.services.client_health import HealthCapabilities, _build_result, compute_health


def _result(**factors):
    values = {
        "communication": None,
        "tasks": None,
        "digests": None,
        "profitability": None,
        "followups": None,
        **factors,
    }
    return _build_result(1, "Cliente", values, {name: "evidencia" for name in values})


def _query_result(*, rows=(), scalar=None):
    result = MagicMock()
    result.all.return_value = list(rows)
    result.scalar.return_value = scalar
    return result


def _client(monthly_budget=None):
    return SimpleNamespace(id=1, name="Cliente", monthly_budget=monthly_budget)


def test_no_available_sources_is_not_classified_as_healthy():
    result = _result()

    assert result["score"] is None
    assert result["risk_level"] == "no_data"
    assert result["enough_information"] is False
    assert result["available_weight"] == 0


def test_one_positive_signal_is_still_insufficient_to_classify_health():
    result = _result(tasks=25)

    assert result["score"] is None
    assert result["risk_level"] == "no_data"
    assert result["available_weight"] == 25


def test_two_factors_from_one_instrument_are_still_insufficient():
    result = _result(communication=25, followups=15)

    assert result["score"] is None
    assert result["risk_level"] == "no_data"
    assert result["available_weight"] == 40
    assert result["available_source_count"] == 1


def test_hidden_communication_does_not_penalize_other_real_evidence():
    result = _result(tasks=25, digests=15, profitability=20)

    assert result["factors"]["communication"] is None
    assert result["factors"]["followups"] is None
    assert result["score"] == 100
    assert result["risk_level"] == "healthy"
    assert result["available_weight"] == 60


def test_real_negative_evidence_still_reports_risk():
    result = _result(tasks=0, digests=0, profitability=0)

    assert result["score"] == 0
    assert result["risk_level"] == "at_risk"


def test_hidden_communications_source_is_unavailable_even_for_admin(monkeypatch):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "communications")
    admin = SimpleNamespace(role=UserRole.admin, permissions=[])

    capabilities = _health_capabilities(admin)

    assert capabilities.communications is False
    assert capabilities.tasks is True
    assert capabilities.digests is True
    assert capabilities.profitability is True


def test_member_without_source_permissions_gets_no_inferred_factors():
    member = SimpleNamespace(role=UserRole.member, permissions=[])

    capabilities = _health_capabilities(member)

    assert capabilities.communications is False
    assert capabilities.tasks is False
    assert capabilities.digests is False
    assert capabilities.profitability is False


def test_hidden_billing_disables_profitability_even_for_admin(monkeypatch):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "billing")
    admin = SimpleNamespace(role=UserRole.admin, permissions=[])

    assert _health_capabilities(admin).profitability is False


@pytest.mark.asyncio
async def test_compute_health_treats_client_without_tasks_as_unmeasured():
    db = AsyncMock()
    db.execute.return_value = _query_result(rows=[])
    capabilities = HealthCapabilities(
        communications=False, tasks=True, digests=False, profitability=False,
    )

    result = await compute_health(_client(), db, capabilities)

    assert result["factors"]["tasks"] is None
    assert result["score"] is None
    assert result["risk_level"] == "no_data"
    assert result["observations"]["tasks"] == "Sin tareas registradas"
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_compute_health_does_not_invent_digest_cadence():
    db = AsyncMock()
    db.execute.return_value = _query_result(scalar=0)
    capabilities = HealthCapabilities(
        communications=False, tasks=False, digests=True, profitability=False,
    )

    result = await compute_health(_client(), db, capabilities)

    assert result["factors"]["digests"] is None
    assert result["observations"]["digests"] == "Sin cadencia de informes acordada"
    assert result["risk_level"] == "no_data"


@pytest.mark.asyncio
async def test_compute_health_exposes_single_observed_risk_without_global_score():
    db = AsyncMock()
    db.execute.side_effect = [
        _query_result(rows=[(TaskStatus.pending, 3)]),
        _query_result(scalar=3),
    ]
    capabilities = HealthCapabilities(
        communications=False, tasks=True, digests=False, profitability=False,
    )

    result = await compute_health(_client(), db, capabilities)

    assert result["score"] is None
    assert result["enough_information"] is False
    assert result["risk_level"] == "at_risk"
    assert result["risk_signals"] == ["3 tareas vencidas"]


@pytest.mark.asyncio
async def test_compute_health_does_not_query_hidden_sources():
    db = AsyncMock()
    capabilities = HealthCapabilities(
        communications=False, tasks=False, digests=False, profitability=False,
    )

    result = await compute_health(_client(monthly_budget=1000), db, capabilities)

    assert result["score"] is None
    db.execute.assert_not_awaited()
