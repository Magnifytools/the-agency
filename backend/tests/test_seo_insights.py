"""Piezas puras del bloque B: variantes de URL, causa de la caída y feed de Google."""
from datetime import date

import pytest

from backend.services import google_search_status
from backend.services.seo_insights import decay_cause, page_variants


def test_variantes_de_una_pagina():
    assert page_variants("https://Acme.com/blog/post?utm_source=x#top") == [
        "https://acme.com/blog/post", "https://acme.com/blog/post/"]
    assert page_variants("https://acme.com/") == ["https://acme.com/"]
    assert page_variants("/blog/post") == []
    assert page_variants("javascript:alert(1)") == []


@pytest.mark.parametrize("current,peak,cause", [
    ({"clicks": 40, "impressions": 2000, "position": 9.5}, {"clicks": 100, "impressions": 2100, "position": 5.0}, "position"),
    ({"clicks": 40, "impressions": 800, "position": 5.2}, {"clicks": 100, "impressions": 2000, "position": 5.0}, "demand"),
    ({"clicks": 40, "impressions": 1900, "position": 5.1}, {"clicks": 100, "impressions": 2000, "position": 5.0}, "ctr"),
])
def test_causa_de_la_caida(current, peak, cause):
    assert decay_cause(current, peak) == cause


def test_el_feed_de_google_se_lee_y_filtra():
    events = google_search_status.parse_incidents([
        {"begin": "2026-09-24T16:15:00+00:00", "end": "2026-10-08T08:00:00+00:00",
         "external_desc": "September 2026 spam update", "service_name": "Ranking", "uri": "incidents/abc"},
        {"begin": "bad", "external_desc": "Sin fecha"},
        {"begin": "2026-08-01T00:00:00+00:00", "external_desc": "", "service_name": "Ranking"},
    ])
    assert len(events) == 1
    assert events[0].start == date(2026, 9, 24) and events[0].end == date(2026, 10, 8)
    assert events[0].kind_label == "Actualización de Google"
    assert events[0].url == "https://status.search.google.com/incidents/abc"


async def test_sin_red_no_rompe_y_lo_dice(monkeypatch):
    google_search_status.clear_cache()

    async def boom():
        raise OSError("sin red")

    monkeypatch.setattr(google_search_status, "_fetch", boom)
    assert await google_search_status.google_events(date(2026, 1, 1), date(2026, 12, 31)) == ([], False)
    google_search_status.clear_cache()
