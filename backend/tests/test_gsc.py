"""Search Console propio: lógica pura (sin BD) y pintado del bloque SEO."""

import base64
import json
from datetime import date

import pytest

from backend.api.routes import google_calendar
from backend.api.routes import gsc as gsc_routes
from backend.schemas.digest import DigestContent
from backend.services import digest_seo
from backend.services.digest_renderer import (
    render_discord,
    render_email,
    render_email_plain,
    render_slack,
)
from backend.services.gsc_service import (
    _changes,
    _email_from_id_token,
    _shift_month,
    is_full_month,
    normalize_site_url,
)

SEO = {
    "status": "ok",
    "site_url": "sc-domain:ejemplo.com",
    "month": {"start": "2026-09-01", "end": "2026-09-30", "days": 30, "clicks": 1234,
              "impressions": 56789, "ctr": 2.17, "position": 12.3},
    "previous": {"start": "2026-08-01", "end": "2026-08-31", "days": 31, "clicks": 1000,
                 "impressions": 50000, "ctr": 2.0, "position": 13.1},
    "year_ago": {"start": "2025-09-01", "end": "2025-09-30", "days": 30, "clicks": 800,
                 "impressions": 40000, "ctr": 2.0, "position": 15.0},
    "vs_previous": {"clicks_pct": 23.4, "impressions_pct": 13.6, "ctr_delta": 0.17, "position_delta": 0.8},
    "vs_year_ago": {"clicks_pct": 54.3, "impressions_pct": 42.0, "ctr_delta": 0.17, "position_delta": 2.7},
}


@pytest.mark.parametrize("raw, expected", [
    ("https://ejemplo.com", "https://ejemplo.com/"),
    ("  https://ejemplo.com/blog/ ", "https://ejemplo.com/blog/"),
    ("sc-domain:ejemplo.com", "sc-domain:ejemplo.com"),
    ("", None),
    (None, None),
])
def test_normalize_site_url(raw, expected):
    assert normalize_site_url(raw) == expected


def test_full_month_only_for_natural_months():
    assert is_full_month(date(2026, 9, 1), date(2026, 9, 30))
    assert is_full_month(date(2028, 2, 1), date(2028, 2, 29))  # bisiesto
    assert not is_full_month(date(2026, 9, 1), date(2026, 9, 7))  # semana
    assert not is_full_month(date(2026, 9, 2), date(2026, 10, 1))


def test_shift_month_crosses_years():
    assert _shift_month(date(2026, 1, 1), -1) == (date(2025, 12, 1), date(2025, 12, 31))
    assert _shift_month(date(2026, 3, 1), -12) == (date(2025, 3, 1), date(2025, 3, 31))


def test_email_from_id_token():
    payload = base64.urlsafe_b64encode(json.dumps({"email": "seo@magnify.ing"}).encode()).decode().rstrip("=")
    assert _email_from_id_token(f"h.{payload}.s") == "seo@magnify.ing"
    assert _email_from_id_token("basura") is None
    assert _email_from_id_token(None) is None


def test_changes_position_positive_means_better():
    current = {"clicks": 120, "impressions": 1000, "ctr": 12.0, "position": 8.0}
    previous = {"clicks": 100, "impressions": 1000, "ctr": 10.0, "position": 10.5}
    assert _changes(current, previous) == {
        "clicks_pct": 20.0, "impressions_pct": 0.0, "ctr_delta": 2.0, "position_delta": 2.5,
    }
    assert _changes(current, None) is None
    # Sin clics previos no hay porcentaje (división por cero)
    assert _changes(current, {**previous, "clicks": 0})["clicks_pct"] is None


def test_headline_is_computed_not_generated():
    assert digest_seo.headline(SEO) == (
        "En septiembre, Google trajo 1.234 visitas orgánicas a la web, un 23,4 % más que en agosto."
    )
    flat = {**SEO, "vs_previous": {**SEO["vs_previous"], "clicks_pct": 0.2}}
    assert digest_seo.headline(flat).endswith("prácticamente las mismas que en agosto.")
    down = {**SEO, "vs_previous": {**SEO["vs_previous"], "clicks_pct": -12.0}}
    assert digest_seo.headline(down).endswith("un 12,0 % menos que en agosto.")
    first = {**SEO, "previous": None, "vs_previous": None}
    assert digest_seo.headline(first) == "En septiembre, Google trajo 1.234 visitas orgánicas a la web."


def test_rows_format_every_metric():
    rows = {r["label"]: r for r in digest_seo.rows(SEO)}
    assert rows["Clics"]["change"] == "+23,4 %" and rows["Clics"]["sign"] == 1
    assert rows["CTR"]["current"] == "2,17 %" and rows["CTR"]["change"] == "+0,17 p. p."
    assert rows["Posición media"]["change"] == "▲ 0,8" and rows["Posición media"]["sign"] == 1


@pytest.mark.parametrize("render", [render_slack, render_discord, render_email_plain, render_email])
def test_every_format_carries_the_block(render):
    out = render(DigestContent(greeting="Hola"), period_start=date(2026, 9, 1),
                 period_end=date(2026, 9, 30), seo=SEO)
    assert "Visibilidad en Google" in out
    assert "1.234" in out and "56.789" in out
    assert "Respecto a septiembre de 2025" in out


@pytest.mark.parametrize("render", [render_slack, render_discord, render_email_plain, render_email])
def test_block_can_be_removed_or_missing(render):
    off = render(DigestContent(include_seo=False), seo=SEO)
    missing = render(DigestContent(), seo={"status": "incomplete"})
    weekly = render(DigestContent(), seo=None)
    for out in (off, missing, weekly):
        assert "Visibilidad en Google" not in out


def test_custom_slack_template_also_gets_the_block():
    out = render_slack(DigestContent(), slack_template={"sections": []}, seo=SEO)
    assert "*Visibilidad en Google · septiembre de 2026*" in out


def test_oauth_state_is_bound_to_search_console():
    state = gsc_routes._sign_state(7)
    assert gsc_routes._verify_state(state) == 7
    # Un state firmado para Calendar no sirve para conectar Search Console.
    with pytest.raises(ValueError):
        gsc_routes._verify_state(google_calendar._sign_oauth_state(7))
