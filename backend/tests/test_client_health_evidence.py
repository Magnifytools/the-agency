"""Health must represent measured evidence, not missing instrumentation."""

from types import SimpleNamespace

from backend.api.routes.clients import _health_capabilities
from backend.db.models import UserRole
from backend.services.client_health import _build_result


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
