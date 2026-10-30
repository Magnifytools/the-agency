"""Informe mensual SEO local: periodos, cálculo de Search Console, ficha, rastreo,
plan, comprobaciones, borrador de IA y la plantilla (sin red ni base de datos).

Las cifras reales de octubre de 2026 (1-26 oct) se comprobaron contra Search
Console en vivo al construirlo (404 clics, 5.817 impresiones, 306 y 319, 203 de
marca y 17 genéricos, 1.230 en toda la web); aquí se prueba el método con datos
inventados y la plantilla con el `datos.json` real de octubre.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from backend.db.models import TaskStatus
from backend.services.local_report import ai, build, gsc, periods, plan, render, sources

FIXTURES = Path(__file__).parent / "fixtures" / "local_report_2026_10"
TEMPLATE = Path(__file__).resolve().parents[1] / "report_templates" / "cigarral"
# HTML del informe entregado de octubre de 2026, sin el PDF incrustado.
REFERENCE_HTML_SHA256 = "18414e793fc889333a4f70de2f6f2891a24f7d8d98562285c92854793018c633"


# ── Periodos ─────────────────────────────────────────────────────────


def test_mes_en_curso_se_compara_con_los_mismos_dias():
    p = periods.compute(date(2026, 10, 1), date(2026, 10, 26))
    assert p.kind == "partial_month"
    assert (p.previous.start, p.previous.end) == (date(2026, 9, 1), date(2026, 9, 26))
    assert (p.year_ago.start, p.year_ago.end) == (date(2025, 10, 1), date(2025, 10, 26))
    assert (p.quarter.start, p.quarter.end) == (date(2026, 8, 1), date(2026, 10, 26))
    assert (p.quarter_year_ago.start, p.quarter_year_ago.end) == (date(2025, 8, 1), date(2025, 10, 26))
    # Sólo meses completos: de julio de 2025 a septiembre de 2026.
    assert p.series_months[0] == "2025-07" and p.series_months[-1] == "2026-09"
    assert len(p.series_months) == 15
    assert p.mes_datos == "2026-10"
    assert p.current.label == "1 al 26 de octubre de 2026"


def test_mes_completo_y_rango_libre():
    p = periods.compute(date(2026, 9, 1), date(2026, 9, 30))
    assert p.kind == "month"
    assert (p.previous.start, p.previous.end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert (p.year_ago.start, p.year_ago.end) == (date(2025, 9, 1), date(2025, 9, 30))
    assert p.series_months[-1] == "2026-09"
    p = periods.compute(date(2026, 3, 1), date(2026, 3, 31))
    assert (p.previous.start, p.previous.end) == (date(2026, 2, 1), date(2026, 2, 28))
    p = periods.compute(date(2026, 10, 10), date(2026, 10, 19))
    assert p.kind == "range"
    assert (p.previous.start, p.previous.end) == (date(2026, 9, 30), date(2026, 10, 9))
    assert p.current.label == "10 al 19 de octubre de 2026"
    assert periods.default_period(date(2026, 11, 5)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert periods.default_period(date(2027, 1, 5)) == (date(2026, 12, 1), date(2026, 12, 31))


# ── Search Console (Google falso) ────────────────────────────────────

LANDING = "https://ejemplo-restaurante.es/restaurante/"
SITE = "https://ejemplo-restaurante.es/"


def _record(day, query, page, clicks, impressions, position=4.0):
    return {"date": day, "query": query, "page": page, "clicks": clicks, "impressions": impressions,
            "position": position}


class FakeGsc:
    """Agrega como Search Console: los totales incluyen lo anonimizado (query None),
    las filas por consulta no."""

    def __init__(self, records):
        self.records = records
        self.calls = 0

    async def __call__(self, *, start_date, end_date, dimensions, filters, row_limit, start_row):
        self.calls += 1
        rows = [r for r in self.records if start_date.isoformat() <= r["date"] <= end_date.isoformat()]
        for f in filters:
            rows = [r for r in rows if r[f["dimension"]] == f["expression"]]
        totals = {"clicks": sum(r["clicks"] for r in rows), "impressions": sum(r["impressions"] for r in rows),
                  "ctr": None, "position": 3.1}
        groups: dict[tuple, dict] = {}
        for r in rows:
            if "query" in dimensions and r["query"] is None:
                continue
            key = tuple(r[d] for d in dimensions)
            acc = groups.setdefault(key, {"keys": dict(zip(dimensions, key)), "clicks": 0, "impressions": 0,
                                          "ctr": None, "position": r["position"]})
            acc["clicks"] += r["clicks"]
            acc["impressions"] += r["impressions"]
        ordered = sorted(groups.values(), key=lambda g: (-g["clicks"], -g["impressions"], str(g["keys"])))
        page = ordered[start_row:start_row + row_limit] if dimensions else []
        has_more = bool(dimensions) and start_row + len(page) < len(ordered)
        return {"rows": page, "totals": totals, "has_more": has_more,
                "next_start_row": start_row + len(page) if has_more else None,
                "data_available_until": end_date.isoformat()}


def _gsc_records():
    out = []
    for day in ("2026-10-03", "2026-10-15"):
        out += [
            _record(day, "caravantes toledo", LANDING, 20, 200),
            _record(day, "Carabante restaurante", LANDING, 5, 50),
            _record(day, "comuniones en toledo", LANDING, 2, 9, 10.8),
            _record(day, "bodas karavan", LANDING, 0, 8),          # parece marca: fuera de grupos
            _record(day, "restaurante con vistas toledo", LANDING, 0, 3, 24.0),
            _record(day, None, LANDING, 30, 100),                  # búsquedas que Google no muestra
            _record(day, None, SITE, 40, 500),
            _record(day, None, SITE + "wp-content/uploads/2026/04/carta.pdf", 6, 30),
        ]
    out += [
        _record("2026-09-10", "caravantes toledo", LANDING, 30, 210),
        _record("2026-09-10", "comuniones en toledo", LANDING, 0, 4),
        _record("2026-09-10", None, LANDING, 10, 40),
        _record("2026-09-10", None, SITE, 50, 400),
        _record("2026-09-10", None, SITE + "wp-content/uploads/2026/04/carta.pdf", 3, 20),
        _record("2025-10-10", "caravantes toledo", LANDING, 9, 300),
        _record("2025-10-10", None, SITE, 35, 600),
        _record("2025-07-15", "caravantes toledo", LANDING, 11, 120),
    ]
    return out


def _gsc_build(fake, *, previous_groups=None, names=None):
    cfg = json.loads((TEMPLATE / "config.json").read_text())["grupos"]
    return asyncio.run(gsc.build(
        fake, landing_url=LANDING, site_url=SITE, brand_terms=["caravantes", "carabante"],
        periods=periods.compute(date(2026, 10, 1), date(2026, 10, 26)), history_start=date(2025, 6, 29),
        group_cfg=cfg, previous_groups=previous_groups, page_names=names or {"/": "Inicio"}))


def test_marca_y_genericas_nunca_reparten_lo_que_google_no_muestra():
    result = _gsc_build(FakeGsc(_gsc_records()))
    g = result["gsc"]
    assert g["clics_mes"] == 2 * (20 + 5 + 2 + 0 + 0 + 30)
    marca, generica = g["intencion_mensual"]["filas"]
    assert (marca["clics"], marca["impresiones"]) == (50, 500)
    assert (generica["clics"], generica["impresiones"]) == (4, 2 * (9 + 8 + 3))
    assert (marca["prev_clics"], generica["prev_clics"]) == (30, 0)
    assert g["clics_mes_anterior"] == 40
    assert g["clics_mismo_mes_ano_anterior"] == 9
    # Histórico: lo oculto es total − visibles.
    assert g["ocultos_clics"] == g["clics_totales_landing"] - g["consultas_visibles_clics"]
    assert g["marca_visibles_clics"] == 50 + 30 + 9 + 11
    assert result["gsc_extra"]["visibles"] == {"actual": 54, "anterior": 30}


def test_grupos_tarjeta_y_tabla():
    result = _gsc_build(FakeGsc(_gsc_records()))
    grupos = result["grupos"]
    # Tarjeta: sin marca y sin "karavan"; las vistas no cuentan.
    assert grupos["resumen_mensual"] == {"impresiones": 18, "impresiones_mes_anterior": 4, "clics": 4}
    queries = [row["q"] for row in grupos["consultas"]]
    # Las dos primeras siempre; las demás sólo con impresiones en algún periodo.
    assert queries[:2] == ["restaurante para eventos toledo", "restaurante para eventos y celebraciones en toledo"]
    assert "comuniones en toledo" in queries and "restaurante con vistas toledo" in queries
    assert "restaurantes en toledo con vistas" not in queries
    row = next(r for r in grupos["consultas"] if r["q"] == "comuniones en toledo")
    assert (row["imp_actual"], row["clics_actual"], row["imp_anterior"]) == (18, 4, 4)
    assert row["intencion"] == "Celebraciones"


def test_grupos_conservan_las_del_mes_anterior_y_suman_las_nuevas():
    records = _gsc_records() + [_record("2026-10-20", "cena de empresa toledo", LANDING, 1, 7)]
    previous = [{"q": "restaurante para eventos toledo", "intencion": "Eventos y grupos"},
                {"q": "algo que se quedó", "intencion": "Eventos y grupos"},
                {"q": "comuniones en toledo", "intencion": "Comuniones (a mano)"}]
    grupos = _gsc_build(FakeGsc(records), previous_groups=previous)["grupos"]["consultas"]
    by_q = {r["q"]: r for r in grupos}
    assert [r["q"] for r in grupos][:2] == ["restaurante para eventos toledo", "algo que se quedó"]
    assert by_q["comuniones en toledo"]["intencion"] == "Comuniones (a mano)"
    assert by_q["cena de empresa toledo"]["intencion"] == "Eventos y grupos"


def test_paginas_de_toda_la_web_con_documentos_que_aun_no_existian():
    g = _gsc_build(FakeGsc(_gsc_records()))["gsc"]
    pages = {p["ruta"]: p for p in g["paginas"]}
    assert pages["/"]["nombre"] == "Inicio" and pages["/"]["clics"] == 80
    pdf = pages["/wp-content/uploads/2026/04/carta.pdf"]
    assert pdf["clics_anterior"] == 3
    assert pdf["clics_ano_anterior"] is None  # subido en abril de 2026: en octubre de 2025 no existía
    assert pages["/restaurante/"]["clics_ano_anterior"] == 9
    assert g["paginas_totales"]["actual"] == sum(r["clicks"] for r in _gsc_records()
                                                 if "2026-10-01" <= r["date"] <= "2026-10-26")


def test_pagina_las_respuestas_largas():
    records = [_record("2026-10-02", f"caravantes {i}", LANDING, 1, 1) for i in range(30)]
    gsc.PAGE_SIZE, old = 7, gsc.PAGE_SIZE
    try:
        fake = FakeGsc(records)
        result = _gsc_build(fake)
    finally:
        gsc.PAGE_SIZE = old
    assert result["gsc"]["intencion_mensual"]["filas"][0]["clics"] == 30


# ── Ficha de Google y rastreo ────────────────────────────────────────


def test_csv_de_la_ficha_de_octubre():
    name = "GBP_restaurante_2026-10-01_2026-10-25.csv"
    parsed = sources.parse_gbp((FIXTURES / name).read_bytes(), name)
    assert parsed["vistas_perfil"] == 2628
    assert (parsed["clics_llamada"], parsed["indicaciones"]) == (64, 268)
    assert parsed["interacciones"] == 64 + 0 + 9 + 268 + 137 + 0 + 15
    assert parsed["periodo"] == "1 al 25 de octubre de 2026"
    assert sources.check_gbp_dates(parsed, date(2026, 10, 1), date(2026, 10, 26)) is None
    # El archivo de septiembre subido como el del año anterior: se avisa.
    name = "GBP_restaurante_2026-09-01_2026-09-25.csv"
    sep = sources.parse_gbp((FIXTURES / name).read_bytes(), name)
    assert sep["vistas_perfil"] == 3580
    assert "se esperaba" in sources.check_gbp_dates(sep, date(2025, 10, 1), date(2025, 10, 26))
    with pytest.raises(sources.SourceError):
        sources.parse_gbp(b"a,b\n1,2\n", "x.csv")


def test_csv_del_rastreo():
    parsed = sources.parse_crawl((FIXTURES / "internal_redirection_3xx_inlinks_2026-10.csv").read_bytes())
    assert (parsed["enlaces_redirigen"], parsed["origenes"], parsed["recurrentes"]) == (2, 1, 0)
    with pytest.raises(sources.SourceError):
        sources.parse_crawl(b"Type,Anchor\nx,y\n")


def test_bloque_de_la_ficha_con_busquedas_pendientes():
    p = periods.compute(date(2026, 10, 1), date(2026, 10, 26))
    name = "GBP_restaurante_2026-10-01_2026-10-25.csv"
    parsed = {"gbp_actual": sources.parse_gbp((FIXTURES / name).read_bytes(), name)}
    settings = json.loads((TEMPLATE / "config.json").read_text())
    google, warnings = build.google_block(parsed, {"busquedas": "Pendiente"}, p,
                                          brand=gsc.BrandMatcher(["caravantes"]), settings=settings)
    assert google["busquedas_que_mostraron_ficha"] == "Pendiente"
    assert google["consultas"][0]["tipo"] == "Google las publica a principios de noviembre"
    assert google["comparativa_mensual"]["interanual"].startswith("No facilitado")
    google, _ = build.google_block(parsed, {"busquedas": 9000, "terminos": [
        {"q": "restaurantes", "apariciones": 5096}, {"q": "cigarral de caravantes", "apariciones": 1540},
        {"q": "hotel cigarral de caravantes", "apariciones": 30}, {"q": "el cigarral toledo", "apariciones": 9}]},
        p, brand=gsc.BrandMatcher(["caravantes"]), settings=settings)
    assert [c["tipo"] for c in google["consultas"]] == ["Genérica", "Marca", "Marca (hotel)", "Cercana a la marca"]


# ── Plan de trabajo ──────────────────────────────────────────────────


def _task(id_, title, status, done=None, waiting=None):
    return plan.PlanTask(id=id_, title=title, status=status, completed_on=done, waiting_for=waiting, retired=False)


def test_plan_desde_las_tareas():
    base = json.loads((TEMPLATE / "roadmap.json").read_text())
    tasks = [
        _task(1191, "E1 - Optimización GBP", TaskStatus.waiting, waiting="Laura: horarios y categoría"),
        _task(1192, "E1 - Redirecciones internas", TaskStatus.completed, date(2026, 10, 27)),
        _task(1193, "E1 - SEO on-page", TaskStatus.in_review),
        _task(1197, "E2 - Schema Restaurant", TaskStatus.completed, date(2026, 11, 20)),
        _task(1999, "E9 - Fuera del plan", TaskStatus.pending),
    ]
    roadmap, warnings, waiting = plan.apply(base, tasks, as_of_day=date(2026, 10, 28))
    october = {t["nombre"]: t for t in roadmap["meses"]["2026-10"]["tareas"]}
    assert october["Redirecciones internas"]["estado"] == "hecho"
    assert october["Redirecciones internas"]["evidencia"] == "The Agency #1192, completada el 27 de octubre de 2026"
    assert october["SEO on-page"]["estado"] == "curso"
    assert october["Optimización GBP"]["estado"] == "bloqueado"
    assert waiting[0]["tarea_id"] == 1191 and waiting[0]["esperando"] == "Laura: horarios y categoría"
    # Completada después de la fecha del informe: seguía prevista.
    assert roadmap["meses"]["2026-11"]["tareas"][0]["estado"] == "previsto"
    assert roadmap["meses"]["2026-10"]["comentario"] is None
    assert any("#1999" in w for w in warnings)
    assert any("Presentación del restaurante" in w for w in warnings)  # no está en The Agency: no se toca
    assert not any("hora" in k.lower() for m in roadmap["meses"].values() for t in m["tareas"] for k in t)
    assert plan.as_of(date(2026, 10, 31), date(2026, 11, 5)) == date(2026, 11, 5)
    assert plan.as_of(date(2026, 7, 31), date(2026, 11, 5)) == date(2026, 7, 31)


def test_plan_conserva_el_motivo_ya_redactado():
    base = json.loads((TEMPLATE / "roadmap.json").read_text())
    tasks = [_task(1191, "E1 - Optimización GBP", TaskStatus.waiting)]
    previous = {"meses": {"2026-10": {"tareas": [{"nombre": "Optimización GBP", "estado": "bloqueado",
                                                  "motivo": "Pendiente de que el restaurante confirme horarios."}]}}}
    roadmap, _, waiting = plan.apply(base, tasks, as_of_day=date(2026, 10, 28), previous=previous)
    task = roadmap["meses"]["2026-10"]["tareas"][0]
    assert task["motivo"] == "Pendiente de que el restaurante confirme horarios."
    assert waiting == []


# ── Comprobaciones y borrador ────────────────────────────────────────


def test_palabras_prohibidas_sin_falsos_positivos():
    datos = {"textos": {"a": "El seguimiento mensual se muestra con detalle.", "b": "Los gráficos muestran meses."}}
    assert render.text_problems(datos, {}) == []
    datos = {"textos": {"a": "Datos de muestra.", "b": "Cifra simulada", "c": "Un dato real", "d": "Por ejemplo",
                        "e": "Con «comillas»", "f": "Uno — otro"}}
    problems = {p["campo"]: p["problema"] for p in render.text_problems(datos, {})}
    assert set(problems) == {"textos.a", "textos.b", "textos.c", "textos.d", "textos.e", "textos.f"}
    roadmap = {"meses": {"2026-10": {"tareas": [{"nombre": "x", "motivo": "Informe de muestra"}]}}}
    assert render.text_problems({}, roadmap)[0]["campo"] == "roadmap.2026-10.tareas[0].motivo"


def test_el_borrador_se_mezcla_y_dice_lo_que_falta():
    datos = json.loads((FIXTURES / "datos.json").read_text())
    roadmap = json.loads((FIXTURES / "roadmap.json").read_text())
    roadmap["meses"]["2026-10"]["tareas"][0]["tarea_id"] = 1191
    keys = render.required_text_keys("cigarral")
    result = {"informe": {"modo": "Datos de octubre de 2026", "nota": "Nota «nueva»."},
              "editorial": {"resumen": "Nuevo resumen.", "analytics": "No debería entrar."},
              "textos": {k: f"Texto {k}" for k in keys[:-1]},
              "tecnico": {"otros": [{"titulo": "Incidencia", "detalle": "d", "estado": "e", "siguiente": "s"}],
                          "filas_rastreo": [{"titulo": "No hay rastreo nuevo"}]},
              "motivos": [{"tarea_id": 1191, "motivo": "Pendiente del restaurante."}]}
    new, new_roadmap, missing = ai.apply_draft(datos, roadmap, result, text_keys=keys,
                                               editorial_keys=list(build.EDITORIAL_KEYS))
    assert new["informe"]["nota"] == "Nota \"nueva\"."
    assert new["editorial"]["resumen"] == "Nuevo resumen."
    assert new["editorial"]["analytics"] == ""  # sin Analytics no hay lectura de Analytics
    assert new["editorial"]["web"] == datos["editorial"]["web"] and "editorial.web" in missing
    assert f"textos.{keys[-1]}" in missing and new["textos"][keys[-1]] == datos["textos"][keys[-1]]
    assert new["tecnico"]["otros"][0]["titulo"] == "Incidencia"
    assert new["tecnico"]["filas_rastreo"] == datos["tecnico"]["filas_rastreo"]
    assert new_roadmap["meses"]["2026-10"]["tareas"][0]["motivo"] == "Pendiente del restaurante."


def test_el_prompt_lleva_reglas_cifras_y_tono():
    datos = json.loads((FIXTURES / "datos.json").read_text())
    datos["contexto"] = {"tareas_en_espera": [{"tarea_id": 1191, "esperando": "horarios"}], "observaciones": "Cierre"}
    roadmap = json.loads((FIXTURES / "roadmap.json").read_text())
    prompt = ai.build_prompt("cigarral", datos, roadmap, text_keys=render.required_text_keys("cigarral"), tone=None)
    assert "Hablar de medir llamadas por procedencia" in prompt
    assert "\"clics_mes\": 404" in prompt
    assert "informe_anterior_para_el_tono" in prompt and "ficha_vistas_pie" in prompt
    assert "tareas_en_espera" in prompt and "observaciones" in prompt


# ── Plantilla (Chromium real; se salta si no está) ───────────────────


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        import os
        with sync_playwright() as p:
            exe = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None)
            p.chromium.launch(executable_path=exe, headless=True, args=["--no-sandbox"]).close()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Chromium/Playwright no disponible")


def _strip_pdf(html: bytes) -> str:
    return re.sub(r'(<script[^>]*id="embedded-pdf"[^>]*>)(.*?)(</script>)', r"\1\3", html.decode(), flags=re.S)


@needs_chromium
def test_octubre_de_2026_sale_igual_que_el_entregado():
    datos = json.loads((FIXTURES / "datos.json").read_text())
    datos["contexto"] = {"clics_total_search_console": 404}
    roadmap = json.loads((FIXTURES / "roadmap.json").read_text())
    out = asyncio.run(render.render("cigarral", datos, roadmap))
    assert out.stem == "Cigarral_Seguimiento_Mensual_2026-Octubre"
    assert out.checks["ok"], out.checks
    assert hashlib.sha256(_strip_pdf(out.html).encode()).hexdigest() == REFERENCE_HTML_SHA256
    embedded = re.search(r'id="embedded-pdf"[^>]*>(.*?)</script>', out.html.decode(), flags=re.S).group(1)
    assert base64.b64decode(embedded.strip()) == out.pdf


@needs_chromium
def test_la_plantilla_sigue_generando_la_demostracion():
    datos = json.loads((TEMPLATE / "datos_ejemplo.json").read_text())
    roadmap = json.loads((TEMPLATE / "roadmap.json").read_text())
    out = asyncio.run(render.render("cigarral", datos, roadmap))
    assert out.stem.startswith("Cigarral_Seguimiento_Mensual_Ejemplo_")
    by_key = {i["clave"]: i for i in out.checks["items"]}
    assert by_key["secciones"]["ok"] and by_key["iconos"]["ok"] and by_key["pdf"]["ok"]


def test_informe_real_sin_textos_no_se_genera():
    datos = json.loads((FIXTURES / "datos.json").read_text())
    datos["textos"].pop("ficha_vistas_pie")
    roadmap = json.loads((FIXTURES / "roadmap.json").read_text())
    with pytest.raises(render.RenderError, match="ficha_vistas_pie"):
        render._render_sync("cigarral", datos, roadmap)
