"""Lo que explica y mide el tráfico de Google de un cliente (Control SEO, bloque B).

- **Anotaciones**: notas a mano, actualizaciones de Google (panel oficial),
  cambios críticos de la web y tareas publicadas, por fecha, para pintarlas
  sobre las gráficas. Cada fuente sólo si quien mira puede leerla.
- **Antes y después**: clics, impresiones y posición en los N días antes y
  después de una fecha, para la web entera, una página o un grupo de URL.
- **Páginas que pierden tráfico**: las que hoy (28 días) están muy por debajo de
  su mejor tramo de 28 días dentro del detalle guardado (120 días).

Todo sale de las tablas propias de Search Console (`gsc_daily`,
`gsc_page_daily`). Nada de esto va a la IA ni al MCP (política de privacidad).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, text

from backend.db.models import Client, SeoAnnotation, Task, User, WebChange, WebWatch
from backend.services import google_search_status
from backend.services.dashboard_access import has_module_read
from backend.services.seo_control import (
    PageGroupMatcher, load_source, pct_change, position_delta, weighted_position, _blocked_payload,
)

ANNOTATION_LIMIT = 200
IMPACT_DAY_CHOICES = (14, 28, 56)
IMPACT_MIN_DAYS = 7
DECAY_WINDOW = 28
DECAY_MIN_PEAK_CLICKS = 30
DECAY_DROP = 0.4  # al menos un 40 % por debajo de su mejor tramo
DECAY_LIMIT = 50


# ── Anotaciones ──────────────────────────────────────────────────────


async def annotations(db, client: Client, user: User, start: date, end: date) -> dict:
    items: list[dict] = []
    # Columnas con hora: tramo [start 00:00, end+1 00:00). Tareas en UTC naive; cambios web con zona.
    naive_from, naive_to = datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)
    aware_from, aware_to = naive_from.replace(tzinfo=timezone.utc), naive_to.replace(tzinfo=timezone.utc)
    manual = (await db.execute(
        select(SeoAnnotation.id, SeoAnnotation.date, SeoAnnotation.text, User.full_name)
        .outerjoin(User, User.id == SeoAnnotation.created_by)
        .where(SeoAnnotation.client_id == client.id, SeoAnnotation.date >= start, SeoAnnotation.date <= end)
        .order_by(SeoAnnotation.date, SeoAnnotation.id)
        .limit(ANNOTATION_LIMIT)
    )).all()
    items += [{"kind": "manual", "id": row.id, "date": row.date.isoformat(), "end_date": None,
               "title": row.text, "author": row.full_name, "href": None} for row in manual]

    google, google_available = await google_search_status.google_events(start, end)
    items += [{"kind": "google", "id": None, "date": e.start.isoformat(),
               "end_date": e.end.isoformat() if e.end else None,
               "title": f"{e.kind_label}: {e.title}", "author": None, "href": e.url} for e in google]

    if has_module_read(user, "web"):
        changes = (await db.execute(
            select(WebChange.id, WebChange.detected_at, WebWatch.url, WebWatch.label)
            .join(WebWatch, WebWatch.id == WebChange.watch_id)
            .where(WebChange.client_id == client.id, WebChange.max_severity == "critical",
                   WebChange.detected_at >= aware_from, WebChange.detected_at < aware_to)
            .order_by(WebChange.detected_at)
            .limit(ANNOTATION_LIMIT)
        )).all()
        items += [{"kind": "web_change", "id": str(row.id), "date": row.detected_at.date().isoformat(),
                   "end_date": None, "title": f"Cambio crítico en {row.label or row.url}",
                   "author": None, "href": f"/web/cambios/{row.id}"} for row in changes]

    if has_module_read(user, "tasks"):
        # Sólo las que tocan una URL: son las que pueden mover el tráfico.
        tasks = (await db.execute(
            select(Task.id, Task.title, Task.completed_at)
            .where(Task.client_id == client.id, Task.completed_at.is_not(None),
                   Task.link_url.is_not(None), Task.link_url != "",
                   Task.completed_at >= naive_from, Task.completed_at < naive_to)
            .order_by(Task.completed_at)
            .limit(ANNOTATION_LIMIT)
        )).all()
        items += [{"kind": "task", "id": row.id, "date": row.completed_at.date().isoformat(),
                   "end_date": None, "title": f"Tarea cerrada: {row.title}", "author": None,
                   "href": f"/tasks?task={row.id}"} for row in tasks]

    items.sort(key=lambda item: (item["date"], item["kind"]))
    return {"items": items, "google_available": google_available}


# ── Antes y después ──────────────────────────────────────────────────


def page_variants(url: str) -> list[str]:
    """La misma página escrita de varias formas: sin query ni fragmento, con y
    sin barra final y con el host en minúsculas (como la guarda Google)."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return []
    path = parts.path or "/"
    base = urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))
    if path == "/":
        return [base]
    return [base.rstrip("/"), base.rstrip("/") + "/"]


@dataclass
class _Totals:
    clicks: int = 0
    impressions: int = 0
    weighted: float = 0.0

    def as_dict(self) -> dict:
        return {"clicks": self.clicks, "impressions": self.impressions,
                "position": _round(weighted_position(self.weighted, self.impressions))}


def _round(value, digits=2):
    return round(value, digits) if value is not None else None


_SITE_IMPACT_SQL = text("""
    SELECT
      COALESCE(SUM(clicks) FILTER (WHERE date < :pivot), 0) AS b_clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date < :pivot), 0) AS b_impressions,
      COALESCE(SUM(position * impressions) FILTER (WHERE date < :pivot), 0) AS b_weighted,
      COALESCE(SUM(clicks) FILTER (WHERE date > :pivot), 0) AS a_clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date > :pivot), 0) AS a_impressions,
      COALESCE(SUM(position * impressions) FILTER (WHERE date > :pivot), 0) AS a_weighted
    FROM gsc_daily
    WHERE site_url = :site AND date >= :start AND date <= :end AND date <> :pivot
""")

_PAGES_IMPACT_SQL = text("""
    SELECT page,
      COALESCE(SUM(clicks) FILTER (WHERE date < :pivot), 0) AS b_clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date < :pivot), 0) AS b_impressions,
      COALESCE(SUM(position::float8 * impressions) FILTER (WHERE date < :pivot), 0) AS b_weighted,
      COALESCE(SUM(clicks) FILTER (WHERE date > :pivot), 0) AS a_clicks,
      COALESCE(SUM(impressions) FILTER (WHERE date > :pivot), 0) AS a_impressions,
      COALESCE(SUM(position::float8 * impressions) FILTER (WHERE date > :pivot), 0) AS a_weighted
    FROM gsc_page_daily
    WHERE site_url = :site AND date >= :start AND date <= :end AND date <> :pivot
    GROUP BY page
""")

_DETAIL_START_SQL = text("SELECT MIN(date) FROM gsc_page_daily WHERE site_url = :site")


async def impact(db, client: Client, *, pivot: date, days: int = 28,
                 page: str | None = None, group: str | None = None) -> dict:
    """Antes = los `days` días antes de `pivot`; después = los mismos días tras
    él (el propio día no cuenta: el cambio pudo ser a mitad). Si aún no han
    pasado `days` días, se comparan tramos iguales con los que haya."""
    source = await load_source(db, client)
    base = {"pivot": pivot.isoformat(), "scope": "page" if page else "group" if group else "site",
            "page": page, "group": group}
    if source.status != "ok":
        return {**_blocked_payload(source), **base, "result": None, "reason": None}
    compared = min(days, (source.end - pivot).days)
    if compared < IMPACT_MIN_DAYS:
        return {**_blocked_payload(source), **base, "result": None, "reason": "too_early",
                "available_from": (pivot + timedelta(days=IMPACT_MIN_DAYS)).isoformat()}
    params = {"site": source.site_url, "pivot": pivot,
              "start": pivot - timedelta(days=compared), "end": pivot + timedelta(days=compared)}

    if not page and not group:
        row = (await db.execute(_SITE_IMPACT_SQL, params)).one()
        before = _Totals(int(row.b_clicks), int(row.b_impressions), float(row.b_weighted))
        after = _Totals(int(row.a_clicks), int(row.a_impressions), float(row.a_weighted))
        pages = None
    else:
        detail_start = await db.scalar(_DETAIL_START_SQL, {"site": source.site_url})
        if detail_start is None or params["start"] < detail_start:
            return {**_blocked_payload(source), **base, "result": None, "reason": "outside_detail",
                    "detail_start": detail_start.isoformat() if detail_start else None}
        rows = (await db.execute(_PAGES_IMPACT_SQL, params)).all()
        if page:
            wanted = set(page_variants(page))
            rows = [r for r in rows if r.page in wanted]
        else:
            matcher = PageGroupMatcher(client.seo_page_groups, source.site_url)
            groups = matcher.assign([r.page for r in rows])
            rows = [r for r in rows if groups[r.page] == group]
        before, after = _Totals(), _Totals()
        for r in rows:
            before.clicks += int(r.b_clicks); before.impressions += int(r.b_impressions); before.weighted += float(r.b_weighted)
            after.clicks += int(r.a_clicks); after.impressions += int(r.a_impressions); after.weighted += float(r.a_weighted)
        pages = len(rows)
        if not rows:
            return {**_blocked_payload(source), **base, "result": None, "reason": "no_data"}

    b, a = before.as_dict(), after.as_dict()
    return {
        **_blocked_payload(source), **base, "reason": None,
        "result": {
            "days": compared,
            "before": {**b, "start": params["start"].isoformat(), "end": (pivot - timedelta(days=1)).isoformat()},
            "after": {**a, "start": (pivot + timedelta(days=1)).isoformat(), "end": params["end"].isoformat()},
            "clicks_change_pct": _round(pct_change(after.clicks, before.clicks), 1),
            "impressions_change_pct": _round(pct_change(after.impressions, before.impressions), 1),
            "position_delta": _round(position_delta(b["position"], a["position"])),
            "pages": pages,
        },
    }


# ── Páginas que pierden tráfico ──────────────────────────────────────

_DECAY_SQL = text("""
    SELECT page, (CAST(:end AS date) - date) / :window AS bucket,
           SUM(clicks) AS clicks, SUM(impressions) AS impressions,
           SUM(position::float8 * impressions) AS weighted
    FROM gsc_page_daily
    WHERE site_url = :site AND date > :floor AND date <= :end
    GROUP BY page, bucket
""")


def decay_cause(current: dict, peak: dict) -> str:
    """Por qué cae: pierde posiciones (empeora ≥ 1), menos búsquedas (las
    impresiones caen tanto como los clics) o menos clics por impresión (el
    resto: título, fragmento o competencia en la página de resultados)."""
    delta = position_delta(peak["position"], current["position"])
    if delta is not None and delta <= -1:
        return "position"
    click_ratio = current["clicks"] / peak["clicks"] if peak["clicks"] else 1.0
    impression_ratio = current["impressions"] / peak["impressions"] if peak["impressions"] else 1.0
    return "demand" if impression_ratio <= click_ratio + 0.15 else "ctr"


async def decaying_pages(db, client: Client, *, limit: int = DECAY_LIMIT) -> dict:
    source = await load_source(db, client)
    if source.status != "ok":
        return {**_blocked_payload(source), "rows": [], "windows": 0}
    detail_start = await db.scalar(_DETAIL_START_SQL, {"site": source.site_url})
    if detail_start is None:
        return {**_blocked_payload(source), "rows": [], "windows": 0}
    windows = min(4, ((source.end - detail_start).days + 1) // DECAY_WINDOW)
    if windows < 2:
        return {**_blocked_payload(source), "rows": [], "windows": windows}
    floor = source.end - timedelta(days=windows * DECAY_WINDOW)
    rows = (await db.execute(_DECAY_SQL, {
        "site": source.site_url, "end": source.end, "floor": floor, "window": DECAY_WINDOW,
    })).all()
    by_page: dict[str, dict[int, dict]] = {}
    for r in rows:
        by_page.setdefault(r.page, {})[int(r.bucket)] = {
            "clicks": int(r.clicks), "impressions": int(r.impressions),
            "position": _round(weighted_position(float(r.weighted), int(r.impressions))),
        }
    empty = {"clicks": 0, "impressions": 0, "position": None}
    out = []
    for page, buckets in by_page.items():
        current = buckets.get(0, empty)
        best_bucket = max(range(1, windows), key=lambda b: buckets.get(b, empty)["clicks"])
        peak = buckets.get(best_bucket, empty)
        if peak["clicks"] < DECAY_MIN_PEAK_CLICKS or current["clicks"] > peak["clicks"] * (1 - DECAY_DROP):
            continue
        peak_end = source.end - timedelta(days=best_bucket * DECAY_WINDOW)
        out.append({
            "page": page,
            "current": current,
            "peak": {**peak, "start": (peak_end - timedelta(days=DECAY_WINDOW - 1)).isoformat(),
                     "end": peak_end.isoformat()},
            "lost_clicks": peak["clicks"] - current["clicks"],
            "drop_pct": _round((current["clicks"] - peak["clicks"]) / peak["clicks"] * 100, 1),
            "cause": decay_cause(current, peak),
        })
    out.sort(key=lambda row: row["lost_clicks"], reverse=True)
    return {**_blocked_payload(source), "rows": out[:limit], "total": len(out), "windows": windows,
            "end": source.end.isoformat(), "window_days": DECAY_WINDOW}
