"""Search Console del informe: página principal, marca, grupos y páginas de la web.

Todo sale de consultas EN VIVO (`gsc_live.query`, que llega aquí como `run`),
nunca de lo guardado: así un mes pasado se puede rehacer mientras Google lo
conserve (16 meses) y lo que se calcula es lo mismo que veía el equipo con la
herramienta `gsc_query` del MCP.

Reglas del proceso (apartado 2 de la skill del informe):
- los clics de búsquedas que Google no muestra (total − suma de consultas)
  nunca se reparten entre marca y genéricas;
- la tarjeta de grupos suma las consultas sin marca de la familia de grupos;
- la tabla de grupos conserva las consultas del mes anterior y añade las
  nuevas con impresiones.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

from backend.services.local_report.periods import ReportPeriods, Window, month_key, short_date
from backend.services.seo_control import BrandMatcher, normalize

PAGE_SIZE = 25000
TOP_PAGES = 10
# Páginas del periodo anterior y del año anterior que se miran para comparar.
COMPARE_PAGE_ROWS = 1000

Run = Callable[..., Awaitable[dict[str, Any]]]


async def _rows(run: Run, window: Window, dimensions: list[str], filters: list[dict],
                *, limit: int | None = None) -> dict[str, Any]:
    """Todas las filas (paginando) y los totales del filtro."""
    rows: list[dict] = []
    start_row = 0
    totals = None
    while True:
        page_size = min(PAGE_SIZE, limit - len(rows)) if limit else PAGE_SIZE
        result = await run(start_date=window.start, end_date=window.end, dimensions=dimensions,
                           filters=filters, row_limit=page_size, start_row=start_row)
        totals = totals or result["totals"]
        rows.extend(result["rows"])
        if not result.get("has_more") or (limit and len(rows) >= limit):
            return {"rows": rows, "totals": totals,
                    "data_available_until": result.get("data_available_until")}
        start_row = result["next_start_row"]


async def _totals(run: Run, window: Window, filters: list[dict]) -> dict[str, Any]:
    result = await run(start_date=window.start, end_date=window.end, dimensions=[],
                       filters=filters, row_limit=1, start_row=0)
    return result["totals"]


def _by_query(rows: list[dict]) -> dict[str, dict]:
    return {r["keys"]["query"]: r for r in rows}


def _split(rows: list[dict], is_brand: BrandMatcher) -> dict[str, list[int]]:
    """{'marca': [clics, impresiones], 'generica': [...]} de las consultas visibles."""
    out = {"marca": [0, 0], "generica": [0, 0]}
    for r in rows:
        key = "marca" if is_brand(r["keys"]["query"]) else "generica"
        out[key][0] += r["clicks"]
        out[key][1] += r["impressions"]
    return out


def _matches(pattern: re.Pattern | None, query: str) -> bool:
    return bool(pattern and pattern.search(normalize(query)))


def compile_family(expression: str | None) -> re.Pattern | None:
    """Familia de consultas (`evento|comuni|…`), sin acentos ni mayúsculas."""
    if not expression:
        return None
    return re.compile(normalize_regex(expression))


def normalize_regex(expression: str) -> str:
    # Sólo alternativas de texto: se normaliza cada una como una consulta.
    return "|".join(re.escape(normalize(part)) for part in expression.split("|") if normalize(part))


def group_intent(query: str, rules: list[dict], default: str) -> str:
    for rule in rules or []:
        if _matches(compile_family(rule.get("pattern")), query):
            return rule["label"]
    return default


# ── Páginas ──────────────────────────────────────────────────────────

_UPLOAD_MONTH = re.compile(r"/uploads/(\d{4})/(\d{2})/")


def page_path(url: str, site: str | None) -> str:
    parts = urlsplit(url)
    path = unquote(parts.path or "/")
    if site and not site.startswith("sc-domain:"):
        site_host = urlsplit(site).hostname
        if site_host and parts.hostname and parts.hostname != site_host:
            return f"{parts.hostname}{path}"
    return path


def existed_by(path: str, window_end: date) -> bool:
    """Un documento subido a /uploads/AAAA/MM/ después del periodo aún no existía."""
    match = _UPLOAD_MONTH.search(path)
    if not match:
        return True
    return (int(match.group(1)), int(match.group(2))) <= (window_end.year, window_end.month)


def humanize_path(path: str) -> str:
    if path in ("", "/"):
        return "Inicio"
    slug = [p for p in path.split("/") if p][-1]
    slug = re.sub(r"\.(pdf|html?|php)$", "", slug, flags=re.I)
    text = re.sub(r"[-_]+", " ", slug).strip()
    return (text[:1].upper() + text[1:]) if text else path


def _pages(current: list[dict], previous: list[dict], year_ago: list[dict], *, site: str | None,
           periods: ReportPeriods, names: dict[str, str]) -> list[dict]:
    def clicks(rows):
        out: dict[str, int] = {}
        for r in rows:
            path = page_path(r["keys"]["page"], site)
            out[path] = out.get(path, 0) + r["clicks"]
        return out

    now, prev, yoy = clicks(current), clicks(previous), clicks(year_ago)
    top = sorted(now.items(), key=lambda item: (-item[1], item[0]))[:TOP_PAGES]
    pages = []
    for path, value in top:
        pages.append({
            "nombre": names.get(path) or humanize_path(path),
            "ruta": path,
            "clics": value,
            "clics_anterior": prev.get(path, 0) if existed_by(path, periods.previous.end) else None,
            "clics_ano_anterior": yoy.get(path, 0) if existed_by(path, periods.year_ago.end) else None,
        })
    return pages


# ── Bloque completo ──────────────────────────────────────────────────


async def build(run: Run, *, landing_url: str, site_url: str | None, brand_terms: list[str],
                periods: ReportPeriods, history_start: date, group_cfg: dict,
                previous_groups: list[dict] | None, page_names: dict[str, str]) -> dict[str, Any]:
    """`gsc` y `grupos` del contrato de datos (más lo que sirve para comprobar)."""
    landing = [{"dimension": "page", "operator": "equals", "expression": landing_url}]
    is_brand = BrandMatcher(list(brand_terms))
    cur, prev, yoy = periods.current, periods.previous, periods.year_ago

    series = await _rows(run, periods.series, ["date"], landing)
    by_month: dict[str, list[int]] = {m: [0, 0] for m in periods.series_months}
    for r in series["rows"]:
        key = r["keys"]["date"][:7]
        if key in by_month:
            by_month[key][0] += r["clicks"]
            by_month[key][1] += r["impressions"]

    t_cur = await _totals(run, cur, landing)
    t_prev = await _totals(run, prev, landing)
    t_yoy = await _totals(run, yoy, landing)
    t_q = await _totals(run, periods.quarter, landing)
    t_q_yoy = await _totals(run, periods.quarter_year_ago, landing)

    q_cur = await _rows(run, cur, ["query"], landing)
    q_prev = await _rows(run, prev, ["query"], landing)
    history = Window(history_start, cur.end)
    q_hist = await _rows(run, history, ["query"], landing)

    s_cur, s_prev, s_hist = _split(q_cur["rows"], is_brand), _split(q_prev["rows"], is_brand), _split(
        q_hist["rows"], is_brand)
    visible_hist = s_hist["marca"][0] + s_hist["generica"][0]

    groups = _groups(q_cur["rows"], q_prev["rows"], q_hist["rows"], is_brand=is_brand, cfg=group_cfg,
                     previous_groups=previous_groups)
    groups["periodo"] = f"{short_date(history.start)} - {short_date(history.end)}, acumulado"

    p_cur = await _rows(run, cur, ["page"], [], limit=COMPARE_PAGE_ROWS)
    p_prev = await _rows(run, prev, ["page"], [], limit=COMPARE_PAGE_ROWS)
    p_yoy = await _rows(run, yoy, ["page"], [], limit=COMPARE_PAGE_ROWS)

    gsc = {
        "mes": periods.mes_datos,
        "clics_mes": t_cur["clicks"],
        "clics_mes_anterior": t_prev["clicks"],
        "clics_mismo_mes_ano_anterior": t_yoy["clicks"],
        "clics_trimestre_actual": t_q["clicks"],
        "clics_trimestre_anterior": t_q_yoy["clicks"],
        "meses_serie": [{"mes": m, "clics": v[0], "impresiones": v[1]} for m, v in by_month.items()],
        "periodo_consultas": f"{short_date(history.start)} - {short_date(history.end)} (16 meses)",
        "clics_totales_landing": q_hist["totals"]["clicks"],
        "consultas_visibles_clics": visible_hist,
        "marca_visibles_clics": s_hist["marca"][0],
        "no_marca_visibles_clics": s_hist["generica"][0],
        "ocultos_clics": max(0, q_hist["totals"]["clicks"] - visible_hist),
        "impresiones_totales_landing": q_hist["totals"]["impressions"],
        "serie_mensual_por_intencion": None,
        "impresiones_mes": t_cur["impressions"],
        "impresiones_mes_anterior": t_prev["impressions"],
        "impresiones_mismo_mes_ano_anterior": t_yoy["impressions"],
        "intencion_mensual": {
            "mes_actual": periods.mes_datos,
            "mes_anterior": month_key(prev.start),
            "filas": [
                {"tipo": "Marca", "clics": s_cur["marca"][0], "prev_clics": s_prev["marca"][0],
                 "impresiones": s_cur["marca"][1], "prev_impresiones": s_prev["marca"][1]},
                {"tipo": "Genéricas y sin marca", "clics": s_cur["generica"][0],
                 "prev_clics": s_prev["generica"][0], "impresiones": s_cur["generica"][1],
                 "prev_impresiones": s_prev["generica"][1]},
            ],
        },
        "paginas": _pages(p_cur["rows"], p_prev["rows"], p_yoy["rows"], site=site_url, periods=periods,
                          names=page_names),
        "paginas_totales": {"actual": p_cur["totals"]["clicks"], "anterior": p_prev["totals"]["clicks"],
                            "ano_anterior": p_yoy["totals"]["clicks"]},
    }
    # Para la redacción y las comprobaciones; la plantilla no los pinta.
    extra = {
        "posicion_media": {"actual": t_cur.get("position"), "anterior": t_prev.get("position"),
                           "ano_anterior": t_yoy.get("position")},
        "ctr": {"actual": t_cur.get("ctr"), "anterior": t_prev.get("ctr"), "ano_anterior": t_yoy.get("ctr")},
        "visibles": {"actual": s_cur["marca"][0] + s_cur["generica"][0],
                     "anterior": s_prev["marca"][0] + s_prev["generica"][0]},
        "consultas_genericas_top": _top_generic(q_cur["rows"], is_brand),
        "data_available_until": q_cur.get("data_available_until"),
    }
    return {"gsc": gsc, "grupos": groups, "gsc_extra": extra}


def _top_generic(rows: list[dict], is_brand: BrandMatcher, limit: int = 15) -> list[dict]:
    generic = [r for r in rows if not is_brand(r["keys"]["query"])]
    generic.sort(key=lambda r: (-r["impressions"], -r["clicks"]))
    return [{"q": r["keys"]["query"], "clics": r["clicks"], "impresiones": r["impressions"],
             "posicion": round(r["position"], 1) if r.get("position") is not None else None}
            for r in generic[:limit]]


def _groups(current: list[dict], previous: list[dict], history: list[dict], *, is_brand: BrandMatcher,
            cfg: dict, previous_groups: list[dict] | None) -> dict[str, Any]:
    exclude = [normalize(x) for x in cfg.get("excluir") or [] if normalize(x)]
    card = compile_family(cfg.get("tarjeta"))
    table = compile_family(cfg.get("tabla"))

    def eligible(query: str, family: re.Pattern | None) -> bool:
        norm = normalize(query)
        return (not is_brand(query) and not any(x in norm for x in exclude) and _matches(family, query))

    now, before, hist = _by_query(current), _by_query(previous), _by_query(history)
    resumen = {"impresiones": 0, "impresiones_mes_anterior": 0, "clics": 0}
    for q, r in now.items():
        if eligible(q, card):
            resumen["impresiones"] += r["impressions"]
            resumen["clics"] += r["clicks"]
    for q, r in before.items():
        if eligible(q, card):
            resumen["impresiones_mes_anterior"] += r["impressions"]

    # Las del mes anterior, en su orden, y las de partida que se quedaron fuera
    # (sin impresiones) por si vuelven a salir.
    base, seen = [], set()
    for item in [*(previous_groups or []), *(cfg.get("consultas_iniciales") or [])]:
        key = normalize(item["q"])
        if key and key not in seen:
            seen.add(key)
            base.append(item)
    min_new = int(cfg.get("min_impresiones_nuevas", 5))
    new = [
        {"q": q, "intencion": group_intent(q, cfg.get("intenciones") or [], cfg.get("intencion_defecto",
                                                                                    "Eventos y grupos"))}
        for q, r in sorted(now.items(), key=lambda item: -item[1]["impressions"])
        if eligible(q, table) and r["impressions"] >= min_new and normalize(q) not in seen
    ]

    rows = []
    for index, item in enumerate([*base, *new]):
        q = item["q"]
        cur, prev, acc = now.get(q), before.get(q), hist.get(q)
        row = {
            "q": q,
            "intencion": item.get("intencion") or cfg.get("intencion_defecto", "Eventos y grupos"),
            "imp_actual": cur["impressions"] if cur else 0,
            "clics_actual": cur["clicks"] if cur else 0,
            "imp_anterior": prev["impressions"] if prev else 0,
            "imp": acc["impressions"] if acc else 0,
            "clics": acc["clicks"] if acc else 0,
            "pos": round(acc["position"], 2) if acc and acc.get("position") is not None else None,
        }
        # Las dos primeras (eventos) se quedan siempre: también salen en "Interés por grupos".
        if index < 2 or row["imp_actual"] or row["imp_anterior"]:
            rows.append(row)
    return {"consultas": rows, "resumen_mensual": resumen}


def history_start(today: date, history_days: int) -> date:
    return today - timedelta(days=history_days)
