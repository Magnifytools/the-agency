"""Semáforo SEO: trend derived from the Engine summary, no stored copy."""
from datetime import datetime

import pytest

from backend.config import settings
from backend.schemas.client import ClientResponse
from backend.services.seo_traffic import seo_traffic


def _summary(clicks, previous, impressions=1000, impressions_previous=1000):
    return {
        "clicks_30d": clicks, "clicks_previous_30d": previous,
        "impressions_30d": impressions, "impressions_previous_30d": impressions_previous,
    }


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 100)


@pytest.mark.parametrize(("clicks", "previous", "trend", "pct"), [
    (120, 100, "up", 20.0),
    (103, 100, "stable", 3.0),
    (90, 100, "down", -10.0),
    (80, 100, "drop_alert", -20.0),   # exactly at the threshold alerts
    (81, 100, "down", -19.0),
    (40, 99, "down", -59.6),          # below the minimum volume: never an alert
    (5, 0, None, None),               # no base to compare
])
def test_trend_bands_and_threshold(clicks, previous, trend, pct):
    traffic = seo_traffic(_summary(clicks, previous))
    assert traffic.trend == trend
    assert traffic.clicks_change_pct == pct


def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 50.0)
    assert seo_traffic(_summary(60, 100)).trend == "down"
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 1000)
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    assert seo_traffic(_summary(60, 100)).trend == "down"


@pytest.mark.parametrize("summary", [
    None, {}, _summary(10, None), _summary(10, True), _summary(-1, 10), _summary(10, 10.5),
])
def test_incomplete_or_invalid_summary_has_no_trend(summary):
    assert seo_traffic(summary) is None


def test_client_response_exposes_flat_sortable_fields():
    now = datetime(2026, 10, 18)
    response = ClientResponse.model_validate({
        "id": 1, "name": "Acme", "contract_type": "monthly", "status": "active",
        "created_at": now, "updated_at": now,
        "engine_summary_data": _summary(500, 1000, 8000, 10000),
    }).model_dump()
    assert response["seo_clicks_change_pct"] == -50.0
    assert response["seo_impressions_change_pct"] == -20.0
    assert response["seo_trend"] == "drop_alert"

    unlinked = ClientResponse.model_validate({
        "id": 2, "name": "Sin Engine", "contract_type": "monthly", "status": "active",
        "created_at": now, "updated_at": now,
    }).model_dump()
    assert unlinked["seo_trend"] is None and unlinked["seo_clicks_change_pct"] is None
