"""Detalle de Search Console del resumen mensual: top de consultas y páginas,
oportunidades y marca frente a sin marca del mes natural del resumen.

Sale de las tablas del detalle (`gsc_query_daily` / `gsc_page_daily`, 120 días)
con las mismas reglas que Control SEO (posición ponderada por impresiones,
marca por subcadena, "sin clasificar" = total − consultas). Se pinta con código
en el email, el PDF, Slack, Discord y el enlace del cliente (`digest_seo`); la IA
no lo ve nunca: no está en `raw_context`, que llega entero al generador.

La foto se guarda en `digest_seo_details`: mientras el resumen no ha salido de
la app se recalcula cada vez que se pinta (así un término de marca nuevo se ve
al momento), y cuando ya salió se lee la guardada, que es lo que se envió.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.models import (
    Client, DigestSeoDetail, GscDetailSync, GscQueryDaily, GscSiteSync, WeeklyDigest,
)
from backend.services import seo_control
from backend.services.gsc_detail_service import coverage_start
from backend.services.gsc_service import is_full_month, normalize_site_url
from backend.services.temporal import business_today

TOP_ROWS = 5
OPPORTUNITY_ROWS = 5
# Final de la primera página y principio de la segunda: con poco trabajo suben.
OPPORTUNITY_MIN_POSITION = 8.0
OPPORTUNITY_MAX_POSITION = 20.0
# Como Control SEO: una posición sobre menos impresiones no dice nada.
MIN_IMPRESSIONS = seo_control.DEFAULT_MIN_IMPRESSIONS


def previous_month_start(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


def display_page(page_url: str, site_url: str) -> str:
    """Ruta legible (sin decodificar no se lee); en propiedades de dominio, con
    el host si no es el principal, porque puede haber varios subdominios."""
    parts = urlsplit(page_url or "")
    path = unquote(parts.path or "/")
    if parts.query:
        path = f"{path}?{unquote(parts.query)}"
    if site_url.startswith("sc-domain:"):
        root = site_url.removeprefix("sc-domain:")
        host = (parts.hostname or "").removeprefix("www.")
        if host and host != root:
            return f"{host}{path}"
    return path


def _row(key: str, agg: seo_control.Agg, *, compare: bool) -> dict:
    position = seo_control.weighted_position(agg.weighted, agg.impressions)
    previous = seo_control.weighted_position(agg.prev_weighted, agg.prev_impressions)
    return {
        "key": key,
        "clicks": agg.clicks,
        "impressions": agg.impressions,
        "position": None if position is None else round(position, 1),
        # Sin el mes anterior entero no hay comparación (ni "nueva").
        "clicks_pct": seo_control.pct_change(agg.clicks, agg.prev_clicks) if compare else None,
        "position_delta": (round(previous - position, 1)
                           if compare and previous is not None and position is not None else None),
        "is_new": compare and agg.prev_impressions <= 0,
    }


def _top(aggregates: dict[str, seo_control.Agg], *, compare: bool) -> list[dict]:
    picked = sorted(
        ((key, agg) for key, agg in aggregates.items() if agg.clicks > 0),
        key=lambda item: (-item[1].clicks, -item[1].impressions, item[0]),
    )[:TOP_ROWS]
    return [_row(key, agg, compare=compare) for key, agg in picked]


def _opportunities(queries: dict[str, seo_control.Agg], matcher: seo_control.BrandMatcher) -> list[dict]:
    picked = []
    for key, agg in queries.items():
        if agg.impressions < MIN_IMPRESSIONS or matcher(key):
            continue
        position = seo_control.weighted_position(agg.weighted, agg.impressions)
        if position is not None and OPPORTUNITY_MIN_POSITION <= position <= OPPORTUNITY_MAX_POSITION:
            picked.append((key, agg, position))
    picked.sort(key=lambda item: (-item[1].impressions, item[2], item[0]))
    return [{"key": key, "clicks": agg.clicks, "impressions": agg.impressions, "position": round(position, 1)}
            for key, agg, position in picked[:OPPORTUNITY_ROWS]]


def _brand(queries: dict[str, seo_control.Agg], totals: seo_control.Agg,
           matcher: seo_control.BrandMatcher, *, compare: bool) -> dict:
    brand = seo_control.Agg()
    non_brand = seo_control.Agg()
    for key, agg in queries.items():
        (brand if matcher(key) else non_brand).add(agg)

    def split(current: bool) -> dict:
        b = brand.clicks if current else brand.prev_clicks
        n = non_brand.clicks if current else non_brand.prev_clicks
        total = totals.clicks if current else totals.prev_clicks
        return {"brand": b, "non_brand": n, "unclassified": seo_control.unclassified(total, b + n)}

    current = split(True)
    previous = split(False) if compare else None
    return {
        **current,
        "previous": previous,
        "non_brand_pct": seo_control.pct_change(current["non_brand"], previous["non_brand"]) if previous else None,
        "brand_pct": seo_control.pct_change(current["brand"], previous["brand"]) if previous else None,
    }


def build(*, site_url: str, month_start: date, month_end: date, compare: bool,
          queries: dict[str, seo_control.Agg], pages: dict[str, seo_control.Agg],
          totals: seo_control.Agg, brand_terms: list[str]) -> dict:
    """La foto del mes a partir de los agregados (puro: lo prueban los tests)."""
    matcher = seo_control.BrandMatcher(list(brand_terms or []))
    top_pages = _top(pages, compare=compare)
    for row in top_pages:
        row["label"] = display_page(row["key"], site_url)
    return {
        "status": "ok",
        "site_url": site_url,
        "month": {"start": month_start.isoformat(), "end": month_end.isoformat()},
        "previous": ({"start": previous_month_start(month_start).isoformat(),
                      "end": (month_start - timedelta(days=1)).isoformat()} if compare else None),
        "queries": _top(queries, compare=compare),
        "pages": top_pages,
        "opportunities": _opportunities(queries, matcher),
        "brand": _brand(queries, totals, matcher, compare=compare) if matcher.terms else None,
    }


async def compute(db, client: Client, month_start: date, month_end: date, *,
                  today: date | None = None) -> dict | None:
    """La foto del mes, o None si no se puede dar entera (sin propiedad, sin el
    detalle de todo el mes o mes que aún no tiene datos finales)."""
    site = normalize_site_url(client.gsc_url)
    if site is None:
        return None
    sync = await db.get(GscSiteSync, site)
    detail = await db.get(GscDetailSync, site)
    if (sync is None or sync.last_data_date is None or sync.last_data_date < month_end
            or detail is None or detail.last_data_date is None or detail.last_data_date < month_end):
        return None
    first_day = await db.scalar(select(func.min(GscQueryDaily.date)).where(GscQueryDaily.site_url == site))
    coverage = coverage_start(first_day, detail.last_data_date, today or business_today())
    if coverage is None or coverage > month_start:
        return None
    previous_start = previous_month_start(month_start)
    compare = coverage <= previous_start
    window = {"start": month_start, "previous_start": previous_start, "end": month_end}
    return build(
        site_url=site, month_start=month_start, month_end=month_end, compare=compare,
        queries=await seo_control.range_aggregates(db, site, dimension="query", **window),
        pages=await seo_control.range_aggregates(db, site, dimension="page", **window),
        totals=await seo_control.range_totals(db, site, **window),
        brand_terms=list(client.brand_terms or []),
    )


async def for_digest(db, digest: WeeklyDigest, *, may_compute: bool) -> dict | None:
    """La foto que se pinta con este resumen.

    `may_compute`: el resumen aún no ha salido de la app → se recalcula y se
    guarda (con commit) si cambió; si ya salió, sólo se lee lo guardado. Un
    resumen que no es de mes natural no lleva detalle.
    """
    if not is_full_month(digest.period_start, digest.period_end):
        return None
    stored = await db.get(DigestSeoDetail, digest.id)
    if not may_compute:
        return stored.payload if stored else None
    client = await db.get(Client, digest.client_id)
    payload = await compute(db, client, digest.period_start, digest.period_end) if client else None
    if payload is None:
        if stored is not None:
            await db.execute(delete(DigestSeoDetail).where(DigestSeoDetail.digest_id == digest.id))
            await db.commit()
        return None
    if stored is None or stored.payload != payload:
        await db.execute(
            pg_insert(DigestSeoDetail)
            .values(digest_id=digest.id, site_url=payload["site_url"], payload=payload)
            .on_conflict_do_update(
                index_elements=[DigestSeoDetail.digest_id],
                set_={"site_url": payload["site_url"], "payload": payload, "computed_at": func.now()},
            )
        )
        await db.commit()
    return payload


async def seo_for_render(db, digest: WeeklyDigest, *, may_compute: bool) -> dict | None:
    """El bloque SEO que reciben los renderizadores: el de `raw_context` (totales)
    con la foto del mes en `detail` cuando la hay."""
    seo = (digest.raw_context or {}).get("seo")
    if not seo or seo.get("status") != "ok":
        return seo
    detail = await for_digest(db, digest, may_compute=may_compute)
    return {**seo, "detail": detail} if detail else seo
