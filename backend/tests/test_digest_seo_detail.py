"""Detalle de Search Console del resumen mensual: la foto del mes y cómo se pinta."""
from __future__ import annotations

import re
import zlib
from datetime import date

from backend.schemas.digest import DigestContent
from backend.services import digest_ga4, digest_pdf, digest_seo, digest_seo_detail
from backend.services.digest_renderer import render_email, render_email_plain, render_slack
from backend.services.seo_control import Agg

SITE = "https://www.ejemplo.com/"


def agg(clicks, impressions, position, prev_clicks=0, prev_impressions=0, prev_position=0.0) -> Agg:
    return Agg(clicks, impressions, position * impressions, prev_clicks, prev_impressions,
               prev_position * prev_impressions)


QUERIES = {
    "zapatillas running": agg(300, 9000, 4.0, 200, 8000, 5.0),
    "ejemplo tienda": agg(250, 1000, 1.2, 260, 1100, 1.1),          # marca
    "zapatillas trail mujer": agg(40, 5000, 9.5, 10, 2000, 14.0),   # oportunidad
    "mejores zapatillas 2026": agg(5, 2500, 15.0),                  # oportunidad, nueva
    "zapatillas baratas": agg(0, 4000, 25.0, 0, 3000, 24.0),        # posición 25: fuera
    "calcetines técnicos": agg(1, 20, 10.0),                        # pocas impresiones
    "ejemplo opiniones": agg(2, 800, 9.0),                          # marca: nunca oportunidad
}
PAGES = {
    "https://www.ejemplo.com/zapatillas/running/": agg(320, 9500, 4.2, 210, 8100, 5.1),
    "https://www.ejemplo.com/": agg(230, 1200, 1.3, 240, 1150, 1.2),
    "https://www.ejemplo.com/blog/guia-trail%C3%B1/": agg(30, 4000, 11.0),
}
TOTALS = Agg(clicks=700, prev_clicks=520)


def build(**overrides):
    params = dict(site_url=SITE, month_start=date(2026, 9, 1), month_end=date(2026, 9, 30), compare=True,
                  queries=QUERIES, pages=PAGES, totals=TOTALS, brand_terms=["Ejemplo"])
    params.update(overrides)
    return digest_seo_detail.build(**params)


# ── La foto ──────────────────────────────────────────────────────────


def test_top_por_clics_con_su_cambio_y_limitado():
    detail = build()
    assert [r["key"] for r in detail["queries"]] == [
        "zapatillas running", "ejemplo tienda", "zapatillas trail mujer",
        "mejores zapatillas 2026", "ejemplo opiniones"]
    first = detail["queries"][0]
    assert (first["clicks"], first["position"], first["clicks_pct"], first["position_delta"]) == (300, 4.0, 50.0, 1.0)
    assert detail["queries"][3]["is_new"] is True and detail["queries"][3]["clicks_pct"] is None
    assert detail["previous"] == {"start": "2026-08-01", "end": "2026-08-31"}
    many = {f"q{i}": agg(100 - i, 1000, 3.0) for i in range(20)}
    assert len(build(queries=many)["queries"]) == digest_seo_detail.TOP_ROWS


def test_paginas_con_ruta_legible():
    pages = build()["pages"]
    assert [p["label"] for p in pages] == ["/zapatillas/running/", "/", "/blog/guia-trailñ/"]
    assert pages[0]["key"] == "https://www.ejemplo.com/zapatillas/running/"


def test_en_propiedad_de_dominio_el_subdominio_se_ve():
    site = "sc-domain:ejemplo.com"
    assert digest_seo_detail.display_page("https://www.ejemplo.com/a", site) == "/a"
    assert digest_seo_detail.display_page("https://ejemplo.com/a", site) == "/a"
    assert digest_seo_detail.display_page("https://blog.ejemplo.com/a?x=1", site) == "blog.ejemplo.com/a?x=1"


def test_oportunidades_entre_8_y_20_sin_marca_y_con_impresiones():
    opportunities = build()["opportunities"]
    assert [o["key"] for o in opportunities] == ["zapatillas trail mujer", "mejores zapatillas 2026"]
    assert opportunities[0] == {"key": "zapatillas trail mujer", "clicks": 40, "impressions": 5000, "position": 9.5}
    # Sin términos de marca, la de marca en posición 9 también es oportunidad.
    assert "ejemplo opiniones" in [o["key"] for o in build(brand_terms=[])["opportunities"]]


def test_marca_sin_marca_y_lo_que_google_no_detalla():
    brand = build()["brand"]
    assert (brand["brand"], brand["non_brand"], brand["unclassified"]) == (252, 346, 102)
    assert brand["previous"] == {"brand": 260, "non_brand": 210, "unclassified": 50}
    assert brand["non_brand_pct"] == 64.8
    assert build(brand_terms=[])["brand"] is None


def test_sin_el_mes_anterior_entero_no_hay_comparacion():
    detail = build(compare=False)
    assert detail["previous"] is None
    assert all(r["clicks_pct"] is None and r["position_delta"] is None and r["is_new"] is False
               for r in detail["queries"] + detail["pages"])
    assert detail["brand"]["previous"] is None and detail["brand"]["non_brand_pct"] is None


def test_mes_anterior_de_enero_es_diciembre():
    assert digest_seo_detail.previous_month_start(date(2027, 1, 1)) == date(2026, 12, 1)


# ── Cómo se pinta ────────────────────────────────────────────────────

SEO = {
    "status": "ok", "site_url": SITE,
    "month": {"start": "2026-09-01", "end": "2026-09-30", "days": 30, "clicks": 700,
              "impressions": 22000, "ctr": 3.18, "position": 8.1},
    "previous": {"start": "2026-08-01", "end": "2026-08-31", "days": 31, "clicks": 520,
                 "impressions": 18000, "ctr": 2.89, "position": 9.0},
    "year_ago": {"start": "2025-09-01", "end": "2025-09-30", "days": 30, "clicks": 400,
                 "impressions": 15000, "ctr": 2.67, "position": 10.2},
    "vs_previous": {"clicks_pct": 34.6, "impressions_pct": 22.2, "ctr_delta": 0.29, "position_delta": 0.9},
    "vs_year_ago": {"clicks_pct": 75.0, "impressions_pct": 46.7, "ctr_delta": 0.51, "position_delta": 2.1},
}


def content(**overrides) -> DigestContent:
    data = {"greeting": "Hola", "sections": {"done": [{"title": "Hecho", "description": "Algo"}], "need": [], "next": []},
            "closing": "Un saludo"}
    data.update(overrides)
    return DigestContent(**data)


def test_interanual_con_las_cuatro_cifras_y_la_posicion_en_palabras():
    line = digest_seo.year_ago_line(SEO)
    assert line == ("Respecto a septiembre de 2025: clics +75,0 %, impresiones +46,7 %, "
                    "CTR +0,51 p. p., posición media mejora 2,1 puestos.")
    worse = {**SEO, "vs_year_ago": {**SEO["vs_year_ago"], "position_delta": -0.4, "ctr_delta": None}}
    assert digest_seo.year_ago_line(worse).endswith("impresiones +46,7 %, posición media empeora 0,4 puestos.")
    assert digest_seo.year_ago_line({**SEO, "year_ago": None}) is None


def test_ga4_interanual():
    ga4 = {"status": "ok",
           "month": {"start": "2026-09-01", "sessions": 4321, "key_events": 87, "ai_sessions": 54},
           "previous": None, "vs_previous": None,
           "year_ago": {"start": "2025-09-01", "sessions": 3000, "key_events": 60, "ai_sessions": 0},
           "vs_year_ago": {"sessions_pct": 44.0, "key_events_pct": 45.0, "ai_sessions_pct": None}}
    assert digest_ga4.year_ago_line(ga4) == "Respecto a septiembre de 2025: visitas +44,0 %, conversiones +45,0 %."
    assert "Respecto a septiembre de 2025" in "\n".join(digest_ga4.render_text(ga4))


def test_sin_detalle_el_bloque_es_el_de_siempre():
    html = render_email(content(), seo=SEO)
    assert digest_seo.QUERIES_TITLE not in html
    assert "Respecto a septiembre de 2025" in html


def test_email_con_el_detalle():
    html = render_email(content(), seo={**SEO, "detail": build()})
    for text in (digest_seo.QUERIES_TITLE, digest_seo.PAGES_TITLE, digest_seo.OPPORTUNITIES_TITLE,
                 digest_seo.BRAND_TITLE, "zapatillas running", "Frente a agosto", "+50,0 %", "nueva",
                 "Sin detallar por Google", 'href="https://www.ejemplo.com/zapatillas/running/"'):
        assert text in html
    # El cliente lo puede quitar entero, totales y detalle.
    assert "zapatillas running" not in render_email(content(include_seo=False), seo={**SEO, "detail": build()})


def test_el_texto_de_una_busqueda_se_escapa():
    nasty = {"<script>x</script>": agg(10, 100, 3.0)}
    html = render_email(content(), seo={**SEO, "detail": build(queries=nasty, brand_terms=[])})
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_texto_plano_y_slack():
    detail = build()
    plain = render_email_plain(content(), seo={**SEO, "detail": detail})
    assert "1. zapatillas running: 300 clics (posición 4,0; +50,0 %)" in plain
    assert "- zapatillas trail mujer: posición 9,5, 5.000 impresiones" in plain
    assert "- Sin la marca: 346 clics (+64,8 %)" in plain
    slack = render_slack(content(), seo={**SEO, "detail": build(compare=False)})
    assert "*Búsquedas que más visitas trajeron*" in slack
    assert "(posición 4,0)" in slack  # sin mes anterior entero, sin cambio


def test_pdf_con_el_detalle():
    data = digest_pdf.render_pdf(content(), client_name="Ejemplo", period_start=date(2026, 9, 1),
                                 period_end=date(2026, 9, 30), seo={**SEO, "detail": build()})
    text = "\n".join(
        zlib.decompress(m.group(1)).decode("cp1252", "replace")
        for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
        if m.group(1)[:1] == b"x")
    for snippet in ("Oportunidades", "zapatillas running", "posici", "mejora", "puestos"):
        assert snippet in text
