"""Organic traffic trend per client, derived from the synced Engine summary.

Engine already sums clicks/impressions over the last 30 days and the 30 days
before (``clicks_previous_30d``), so nothing extra is stored here: the trend is
read from ``Client.engine_summary_data`` by the client list and by the
``client_seo_traffic_drop`` incident condition, which must agree.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Float, and_, case, cast, func

from backend.config import settings

SeoTrend = Literal["up", "stable", "down", "drop_alert"]

# Same band Engine uses for its own "stable" trend.
STABLE_BAND_PCT = 5.0


@dataclass(frozen=True)
class SeoTraffic:
    clicks: int
    clicks_previous: int
    impressions: int
    impressions_previous: int
    clicks_change_pct: float | None
    impressions_change_pct: float | None
    trend: SeoTrend | None


def _count(summary: dict, key: str) -> int | None:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _min_previous_clicks() -> int:
    return max(settings.SEO_DROP_MIN_CLICKS, 1)


def is_traffic_drop(clicks: int, clicks_previous: int) -> bool:
    """Alert only on a real drop over a meaningful base, never on noise."""
    if clicks_previous < _min_previous_clicks():
        return False
    return clicks <= clicks_previous * (1 - settings.SEO_DROP_ALERT_PCT / 100)


def seo_traffic(summary: object) -> SeoTraffic | None:
    if not isinstance(summary, dict):
        return None
    values = [_count(summary, key) for key in (
        "clicks_30d", "clicks_previous_30d", "impressions_30d", "impressions_previous_30d",
    )]
    if any(value is None for value in values):
        return None
    clicks, clicks_previous, impressions, impressions_previous = values
    change = _change(clicks, clicks_previous)
    if is_traffic_drop(clicks, clicks_previous):
        trend: SeoTrend | None = "drop_alert"
    elif change is None:
        trend = None
    elif change > STABLE_BAND_PCT:
        trend = "up"
    elif change < -STABLE_BAND_PCT:
        trend = "down"
    else:
        trend = "stable"
    return SeoTraffic(
        clicks, clicks_previous, impressions, impressions_previous,
        change, _change(impressions, impressions_previous), trend,
    )


def traffic_drop_clause(summary_column):
    """SQL twin of ``is_traffic_drop`` over the JSONB summary column."""
    def value(key):
        return cast(summary_column[key].astext, Float)

    return and_(
        func.jsonb_typeof(summary_column["clicks_30d"]) == "number",
        func.jsonb_typeof(summary_column["clicks_previous_30d"]) == "number",
        value("clicks_previous_30d") >= _min_previous_clicks(),
        value("clicks_30d") <= value("clicks_previous_30d") * (1 - settings.SEO_DROP_ALERT_PCT / 100),
    )


def clicks_change_expr(summary_column):
    """SQL ratio of clicks vs the previous 30 days; NULL without a valid base."""
    def value(key):
        return cast(summary_column[key].astext, Float)

    return case(
        (
            and_(
                func.jsonb_typeof(summary_column["clicks_30d"]) == "number",
                func.jsonb_typeof(summary_column["clicks_previous_30d"]) == "number",
                value("clicks_previous_30d") > 0,
            ),
            (value("clicks_30d") - value("clicks_previous_30d")) / value("clicks_previous_30d"),
        ),
        else_=None,
    )
