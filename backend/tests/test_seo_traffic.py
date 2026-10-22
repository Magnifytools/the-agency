"""Semáforo SEO: bandas, umbral y ventana compartida (Search Console propio)."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from backend.config import settings
from backend.schemas.client import ClientResponse
from backend.services import seo_traffic as st
from backend.services.seo_control import seo_window
from backend.services.seo_traffic import seo_traffic


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 100)


@pytest.mark.parametrize(("clicks", "previous", "trend", "pct"), [
    (120, 100, "up", 20.0),
    (103, 100, "stable", 3.0),
    (90, 100, "down", -10.0),
    (80, 100, "drop_alert", -20.0),   # justo en el umbral, alerta
    (81, 100, "down", -19.0),
    (40, 99, "down", -59.6),          # sin volumen mínimo nunca es alerta
    (5, 0, None, None),               # sin base no hay comparación
])
def test_trend_bands_and_threshold(clicks, previous, trend, pct):
    traffic = seo_traffic(clicks, previous, 1000, 1000)
    assert traffic.trend == trend
    assert traffic.clicks_change_pct == pct


def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 50.0)
    assert seo_traffic(60, 100, 0, 0).trend == "down"
    monkeypatch.setattr(settings, "SEO_DROP_MIN_CLICKS", 1000)
    monkeypatch.setattr(settings, "SEO_DROP_ALERT_PCT", 20.0)
    assert seo_traffic(60, 100, 0, 0).trend == "down"


def test_impressions_change_and_no_base():
    traffic = seo_traffic(500, 1000, 8000, 10000)
    assert traffic.impressions_change_pct == -20.0
    assert seo_traffic(500, 1000, 10, 0).impressions_change_pct is None


def test_sql_window_offsets_come_from_the_shared_window():
    """La versión SQL usa los mismos 28 + 28 días que el estado y Control SEO."""
    end = date(2026, 10, 16)
    window = seo_window(end)
    assert (end - window.start).days == st._START_BACK == 27
    assert (end - window.previous_start).days == st._PREVIOUS_BACK == 55


def test_client_response_reads_attached_trend_and_defaults_to_null():
    now = datetime(2026, 10, 18)
    base = {"id": 1, "name": "Acme", "contract_type": "monthly", "status": "active",
            "created_at": now, "updated_at": now}
    response = ClientResponse.model_validate({
        **base, "seo_clicks_change_pct": -50.0, "seo_impressions_change_pct": -20.0,
        "seo_trend": "drop_alert",
    }).model_dump()
    assert response["seo_trend"] == "drop_alert" and response["seo_clicks_change_pct"] == -50.0

    # Desde el ORM sin `attach_seo_traffic`: los campos quedan a null, no fallan.
    orm_like = SimpleNamespace(**base, brand_terms=[])
    assert ClientResponse.model_validate(orm_like).seo_trend is None
