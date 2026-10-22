"""Semáforo SEO: tráfico orgánico de cada cliente desde nuestro Search Console.

Lee `gsc_daily` de la propiedad del cliente (`Client.gsc_url`) con la MISMA
ventana que el estado del cliente y Control SEO (`seo_window`: los 28 días
hasta el último día con datos finales de `gsc_site_sync` y los 28 anteriores).
Nada se guarda aparte: la lista de clientes (y su orden), la incidencia
``client_seo_traffic_drop`` y el estado del cliente calculan lo mismo aquí.

The Engine está congelado (21 oct 2026): nada de esto lee
``Client.engine_summary_data``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal

from sqlalchemy import Float, and_, case, cast, func, or_, select

from backend.config import settings
from backend.db.models import Client, GscDaily, GscSiteSync
from backend.services.seo_control import seo_window

SeoTrend = Literal["up", "stable", "down", "drop_alert"]

# ±5 %: estable.
STABLE_BAND_PCT = 5.0

# Desfases de la ventana compartida, sacados del propio `seo_window` para que
# la versión SQL no pueda separarse de la de Python.
_SAMPLE = seo_window(date(2000, 1, 1))
_START_BACK = (_SAMPLE.end - _SAMPLE.start).days
_PREVIOUS_BACK = (_SAMPLE.end - _SAMPLE.previous_start).days


@dataclass(frozen=True)
class SeoTraffic:
    clicks: int
    clicks_previous: int
    impressions: int
    impressions_previous: int
    clicks_change_pct: float | None
    impressions_change_pct: float | None
    trend: SeoTrend | None
    as_of: date | None = None


def _change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _min_previous_clicks() -> int:
    return max(settings.SEO_DROP_MIN_CLICKS, 1)


def is_traffic_drop(clicks: int, clicks_previous: int) -> bool:
    """Sólo una caída real sobre una base con volumen, nunca ruido."""
    if clicks_previous < _min_previous_clicks():
        return False
    return clicks <= clicks_previous * (1 - settings.SEO_DROP_ALERT_PCT / 100)


def trend_of(clicks: int, clicks_previous: int) -> SeoTrend | None:
    if is_traffic_drop(clicks, clicks_previous):
        return "drop_alert"
    change = _change(clicks, clicks_previous)
    if change is None:
        return None
    if change > STABLE_BAND_PCT:
        return "up"
    if change < -STABLE_BAND_PCT:
        return "down"
    return "stable"


def seo_traffic(
    clicks: int, clicks_previous: int, impressions: int, impressions_previous: int,
    as_of: date | None = None,
) -> SeoTraffic:
    return SeoTraffic(
        clicks, clicks_previous, impressions, impressions_previous,
        _change(clicks, clicks_previous), _change(impressions, impressions_previous),
        trend_of(clicks, clicks_previous), as_of,
    )


# ── SQL ──────────────────────────────────────────────────────────────


def site_url_expr(column):
    """Gemelo SQL de `gsc_service.normalize_site_url` (la clave de `gsc_daily`)."""
    site = func.btrim(column, " \t\r\n")
    return case(
        (or_(column.is_(None), site == ""), None),
        (site.startswith("sc-domain:"), site),
        (
            and_(or_(site.startswith("http://"), site.startswith("https://")), ~site.endswith("/")),
            site + "/",
        ),
        else_=site,
    )


def site_totals():
    """Clics e impresiones por propiedad en la ventana compartida. Una agregación.

    Sólo propiedades con el histórico importado y un último día con datos: sin
    eso no hay ventana que comparar (igual que el estado del cliente).
    """
    end = GscSiteSync.last_data_date
    recent = GscDaily.date >= end - _START_BACK

    def total(column, current: bool):
        return func.coalesce(func.sum(column).filter(recent if current else ~recent), 0)

    return (
        select(
            GscSiteSync.site_url.label("site_url"),
            end.label("as_of"),
            total(GscDaily.clicks, True).label("clicks"),
            total(GscDaily.clicks, False).label("clicks_previous"),
            total(GscDaily.impressions, True).label("impressions"),
            total(GscDaily.impressions, False).label("impressions_previous"),
        )
        .select_from(GscSiteSync)
        .outerjoin(GscDaily, and_(
            GscDaily.site_url == GscSiteSync.site_url,
            GscDaily.date >= end - _PREVIOUS_BACK,
            GscDaily.date <= end,
        ))
        .where(GscSiteSync.backfilled_at.isnot(None), end.isnot(None))
        .group_by(GscSiteSync.site_url, end)
    )


def client_traffic(client_ids: Iterable[int] | None = None):
    """Subconsulta: una fila por cliente con propiedad y datos (`client_id` + cifras)."""
    totals = site_totals().subquery()
    query = select(
        Client.id.label("client_id"), totals.c.as_of, totals.c.clicks, totals.c.clicks_previous,
        totals.c.impressions, totals.c.impressions_previous,
    ).join(totals, totals.c.site_url == site_url_expr(Client.gsc_url))
    if client_ids is not None:
        query = query.where(Client.id.in_(list(client_ids)))
    return query.subquery("seo_traffic")


def clicks_change_expr(traffic):
    """Variación de clics (ratio) sobre la subconsulta; NULL sin base."""
    return case(
        (traffic.c.clicks_previous > 0,
         (traffic.c.clicks - traffic.c.clicks_previous) / cast(traffic.c.clicks_previous, Float)),
        else_=None,
    )


def traffic_drop_clause(traffic):
    """Gemelo SQL de `is_traffic_drop` sobre la subconsulta."""
    return and_(
        traffic.c.clicks_previous >= _min_previous_clicks(),
        traffic.c.clicks <= traffic.c.clicks_previous * (1 - settings.SEO_DROP_ALERT_PCT / 100),
    )


def _from_row(row) -> SeoTraffic:
    return seo_traffic(
        int(row.clicks), int(row.clicks_previous), int(row.impressions), int(row.impressions_previous),
        row.as_of,
    )


async def traffic_by_client(db, client_ids: Iterable[int]) -> dict[int, SeoTraffic]:
    ids = list(client_ids)
    if not ids:
        return {}
    traffic = client_traffic(ids)
    rows = (await db.execute(select(traffic))).all()
    return {row.client_id: _from_row(row) for row in rows}


async def traffic_by_site(db, sites: Iterable[str]) -> dict[str, SeoTraffic]:
    wanted = [s for s in sites if s]
    if not wanted:
        return {}
    totals = site_totals().where(GscSiteSync.site_url.in_(wanted)).subquery()
    rows = (await db.execute(select(totals))).all()
    return {row.site_url: _from_row(row) for row in rows}


async def attach_seo_traffic(db, clients: list[Client]) -> None:
    """Deja el semáforo en cada cliente para `ClientResponse` (una consulta)."""
    traffic = await traffic_by_client(db, [c.id for c in clients])
    for client in clients:
        t = traffic.get(client.id)
        client.seo_clicks_change_pct = t.clicks_change_pct if t else None
        client.seo_impressions_change_pct = t.impressions_change_pct if t else None
        client.seo_trend = t.trend if t else None
