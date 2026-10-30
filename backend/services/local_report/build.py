"""Montar el `datos.json` de un informe con lo que calcula The Agency y lo que sube el equipo.

Al recalcular una versión se conserva lo que el equipo ya escribió o revisó
(textos, lectura de cada sección, filas técnicas, motivos de espera): sólo se
sustituyen las cifras.
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from backend.services.local_report import ga4 as ga4_block
from backend.services.local_report import gsc as gsc_block
from backend.services.local_report import plan as plan_block
from backend.services.local_report.periods import MONTHS, ReportPeriods, add_months, long_date, range_label
from backend.services.local_report.sources import check_gbp_dates
from backend.services.seo_control import BrandMatcher, normalize

GBP_KINDS = ("gbp_actual", "gbp_anterior", "gbp_ano_anterior")
# Las lecturas que pinta la plantilla (`nota_final` del contrato antiguo no sale en la v6).
EDITORIAL_KEYS = ("resumen", "web", "paginas", "intencion", "grupos", "maps", "negocio", "tecnico", "analytics")
_GBP_FIELDS = ("vistas_perfil", "interacciones", "clics_llamada", "indicaciones", "clics_web",
               "acciones_reserva", "clics_carta")


def site_parts(landing_url: str) -> tuple[str, str]:
    parts = urlsplit(landing_url)
    return f"{parts.scheme}://{parts.netloc}/", parts.path or "/"


def default_mode(periods: ReportPeriods, today: date) -> str:
    cur = periods.current
    if periods.full_month:
        return f"Datos de {MONTHS[cur.start.month - 1]} de {cur.start.year}"
    if (cur.end.year, cur.end.month) == (today.year, today.month):
        return f"Datos del {range_label(cur.start, cur.end)} (mes en curso)"
    return f"Datos del {range_label(cur.start, cur.end)}"


# ── Ficha de Google ──────────────────────────────────────────────────


def classify_gbp_term(term: str, brand: BrandMatcher, settings: dict) -> str:
    ficha = settings.get("ficha") or {}
    norm = normalize(term)
    if brand(term):
        secondary = ficha.get("marca_secundaria") or {}
        if any(normalize(t) in norm for t in secondary.get("terminos") or []):
            return secondary.get("tipo") or "Marca"
        return "Marca"
    if any(normalize(t) in norm for t in ficha.get("cercanas_a_marca") or []):
        return "Cercana a la marca"
    return "Genérica"


def google_block(parsed: dict[str, dict], inputs: dict, periods: ReportPeriods, *, brand: BrandMatcher,
                 settings: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    expected = {"gbp_actual": periods.current, "gbp_anterior": periods.previous,
                "gbp_ano_anterior": periods.year_ago}
    for kind, window in expected.items():
        if kind in parsed:
            problem = check_gbp_dates(parsed[kind], window.start, window.end)
            if problem:
                warnings.append(f"Ficha de Google ({_GBP_LABEL[kind]}): {problem}")
    now = parsed.get("gbp_actual")
    prev = parsed.get("gbp_anterior")
    yoy = parsed.get("gbp_ano_anterior")
    if now is None:
        warnings.append("Falta el CSV de la ficha de Google del periodo: las tarjetas de la ficha saldrán sin dato.")

    google: dict[str, Any] = {"periodo": (now or {}).get("periodo") or "periodo no facilitado"}
    for field in _GBP_FIELDS:
        google[field] = (now or {}).get(field)

    month_name = MONTHS[periods.current.start.month - 1]
    searches = inputs.get("busquedas")
    if searches == "Pendiente":
        next_month = MONTHS[add_months(periods.current.start, 1).month - 1]
        google["busquedas_que_mostraron_ficha"] = "Pendiente"
        google["consultas"] = [{"q": f"Búsquedas de {month_name}", "apariciones": "Pendiente",
                                "tipo": f"Google las publica a principios de {next_month}"}]
    else:
        google["busquedas_que_mostraron_ficha"] = searches if isinstance(searches, int) else None
        google["consultas"] = [
            {"q": t["q"], "apariciones": t["apariciones"],
             "tipo": t.get("tipo") or classify_gbp_term(t["q"], brand, settings)}
            for t in inputs.get("terminos") or []
        ]
        if searches is None:
            warnings.append("Falta la cifra de búsquedas que mostraron la ficha (o márcala como pendiente).")
    if now and searches not in (None, "Pendiente") and inputs.get("personas_panel") not in (None, now["vistas_perfil"]):
        warnings.append(
            f"La captura dice {inputs['personas_panel']} personas y el CSV suma {now['vistas_perfil']}: "
            "las fechas del panel no son las pedidas.")

    comparison: dict[str, Any] = {"periodo_anterior": (prev or {}).get("periodo")}
    for field in _GBP_FIELDS:
        comparison[field] = (prev or {}).get(field)
    comparison["vistas_por_superficie"] = {"actual": (now or {}).get("vistas_por_superficie"),
                                           "anterior": (prev or {}).get("vistas_por_superficie")}
    if yoy:
        comparison["interanual"] = {"periodo": yoy.get("periodo"), **{f: yoy.get(f) for f in _GBP_FIELDS},
                                    "vistas_por_superficie": yoy.get("vistas_por_superficie")}
    else:
        comparison["interanual"] = f"No facilitado (exportación del {periods.year_ago.label} pendiente)"
    google["comparativa_mensual"] = comparison
    return google, warnings


_GBP_LABEL = {"gbp_actual": "periodo", "gbp_anterior": "periodo anterior", "gbp_ano_anterior": "año anterior"}


# ── Rastreo ──────────────────────────────────────────────────────────


def tecnico_block(base: dict, crawl: dict | None, inputs: dict, periods: ReportPeriods) -> dict:
    tecnico = copy.deepcopy(base)
    tecnico["mes_actual"] = periods.mes_datos
    if crawl:
        tecnico["enlaces_redirigen"] = crawl["enlaces_redirigen"]
        tecnico["origenes"] = crawl["origenes"]
        tecnico["recurrentes"] = crawl["recurrentes"]
        crawl_day = inputs.get("fecha_rastreo")
        if crawl_day:
            tecnico["fecha_ultimo_crawl"] = long_date(date.fromisoformat(crawl_day))
        tecnico["rastreo_nuevo"] = {k: crawl[k] for k in ("enlaces_redirigen", "origenes", "destinos",
                                                          "recurrentes", "por_posicion", "ejemplos")}
    else:
        tecnico.pop("rastreo_nuevo", None)
    tecnico.setdefault("filas_rastreo", [])
    tecnico.setdefault("otros", [])
    return tecnico


# ── Todo junto ───────────────────────────────────────────────────────


async def build(*, settings: dict, landing_url: str, roadmap_base: dict, brand_terms: list[str],
                periods: ReportPeriods, today: date, history_start: date, gsc_run, ga4_run,
                tasks: list[plan_block.PlanTask], parsed_sources: dict[str, dict], inputs: dict,
                current: dict | None, current_roadmap: dict | None, previous: dict | None,
                previous_roadmap: dict | None) -> tuple[dict, dict, list[str]]:
    """(datos, roadmap, avisos). `current` es la versión que se recalcula (se
    conservan sus textos); `previous`, la última versión de un periodo anterior."""
    warnings: list[str] = []
    web, landing_path = site_parts(landing_url)
    brand = BrandMatcher(list(brand_terms))
    if not brand_terms:
        warnings.append("El cliente no tiene términos de marca (Ajustes → Control SEO): todo cuenta como genérico.")

    prev_groups = [{"q": q["q"], "intencion": q.get("intencion")}
                   for q in ((previous or {}).get("grupos") or {}).get("consultas") or []] or None
    page_names = {**(settings.get("nombres_paginas") or {})}
    for page in ((previous or {}).get("gsc") or {}).get("paginas") or []:
        page_names.setdefault(page["ruta"], page["nombre"])
    for page in ((current or {}).get("gsc") or {}).get("paginas") or []:
        page_names[page["ruta"]] = page["nombre"]  # un nombre corregido a mano se respeta

    computed = await gsc_block.build(gsc_run, landing_url=landing_url, site_url=web, brand_terms=brand_terms,
                                     periods=periods, history_start=history_start,
                                     group_cfg=settings.get("grupos") or {}, previous_groups=prev_groups,
                                     page_names=page_names)
    if current:
        # Intención de cada consulta de grupos corregida a mano: se respeta.
        edited = {normalize(q["q"]): q.get("intencion") for q in (current.get("grupos") or {}).get("consultas") or []}
        for row in computed["grupos"]["consultas"]:
            row["intencion"] = edited.get(normalize(row["q"])) or row["intencion"]

    if ga4_run is not None:
        try:
            ga4 = await ga4_run(periods)
        except Exception as exc:  # noqa: BLE001 — sin Analytics el informe sale igual
            warnings.append(f"Google Analytics: {getattr(exc, 'message', None) or exc}")
            ga4 = {"disponible": False}
    else:
        ga4 = {"disponible": False}
        warnings.append("El cliente no tiene propiedad de Google Analytics: la sección de tráfico sale pendiente.")

    google, google_warnings = google_block(parsed_sources, inputs, periods, brand=brand, settings=settings)
    warnings += google_warnings

    base_tecnico = (current or {}).get("tecnico") or (previous or {}).get("tecnico") or settings.get("tecnico") or {}
    tecnico = tecnico_block(base_tecnico, parsed_sources.get("rastreo"), inputs, periods)

    as_of = plan_block.as_of(periods.current.end, today)
    roadmap, plan_warnings, waiting = plan_block.apply(
        roadmap_base, tasks, as_of_day=as_of, previous=current_roadmap or previous_roadmap)
    warnings += plan_warnings

    informe_prev = (current or {}).get("informe") or {}
    datos = {
        "cliente": {**(settings.get("cliente") or {}), "web": web, "landing": landing_path},
        "informe": {
            "mes_datos": periods.mes_datos,
            "fecha_documento": long_date(today),
            "mes_roadmap_preferido": periods.mes_datos if periods.mes_datos in (roadmap.get("meses") or {}) else None,
            "modo": informe_prev.get("modo") or default_mode(periods, today),
            "nota": informe_prev.get("nota") or "",
            "es_demo": False,
        },
        "gsc": computed["gsc"],
        "grupos": computed["grupos"],
        "google": google,
        "tecnico": tecnico,
        "editorial": {k: ((current or {}).get("editorial") or {}).get(k, "") for k in EDITORIAL_KEYS},
        "textos": dict((current or {}).get("textos") or {}),
        "ga4": ga4,
        "contexto": {
            **computed["gsc_extra"],
            "clics_total_search_console": computed["gsc"]["clics_mes"],
            "periodos": {"actual": periods.current.as_dict(), "anterior": periods.previous.as_dict(),
                         "ano_anterior": periods.year_ago.as_dict(), "trimestre": periods.quarter.as_dict(),
                         "trimestre_ano_anterior": periods.quarter_year_ago.as_dict(), "tipo": periods.kind},
            "plan_a_fecha": as_of.isoformat(),
            "tareas_en_espera": waiting,
            "observaciones": inputs.get("observaciones") or "",
        },
    }
    editorial = datos["editorial"]
    editorial["prioridades"] = []
    if not ga4.get("disponible"):
        editorial["analytics"] = ""
    return datos, roadmap, warnings


def ga4_runner(query_fn):
    """Adapta `ga4_live.query` (ya atado a la BD y al cliente) a `ga4_block.build`."""
    async def run(periods: ReportPeriods) -> dict:
        return await ga4_block.build(query_fn, periods)
    return run
