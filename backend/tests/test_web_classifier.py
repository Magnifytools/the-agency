"""Clasificación de cambios (portado de Vigil, tests/test_classifier.py)."""
from __future__ import annotations

from backend.services.web.classifier import CRITICAL, INFO, WARNING, classify, max_severity

BASE_SEO = {
    "status_code": 200,
    "final_url": "https://fitgeneration.es/master",
    "title": "Máster en Nutrición | Fit Generation",
    "meta_description": "Fórmate con los mejores.",
    "h1": ["Máster en Nutrición"],
    "h2": ["Temario", "Salidas profesionales"],
    "canonical": "https://fitgeneration.es/master",
    "meta_robots": "index, follow",
    "x_robots_tag": "",
    "robots_directives": ["follow", "index"],
    "hreflang": [],
    "schema_types": ["Course"],
    "lang": "es",
    "word_count": 1200,
}


def seo(**cambios):
    return {**BASE_SEO, **cambios}


def codes(items):
    return [i.rule_code for i in items]


# --------------------------------------------------------------------------
# La regla que evita 100 avisos el primer día
# --------------------------------------------------------------------------

def test_primera_captura_no_genera_ningun_cambio():
    """Sin estado anterior no hay nada que comparar. Si esto se rompe, dar de
    alta un sitemap de 100 URLs dispara 100 avisos la primera noche."""
    assert classify(prev_seo=None, curr_seo=seo()) == []


def test_sin_cambios_no_genera_nada():
    """La regla que sostiene 'sin cambios → no llega mensaje'."""
    assert classify(prev_seo=seo(), curr_seo=seo()) == []


# --------------------------------------------------------------------------
# Críticos
# --------------------------------------------------------------------------

def test_noindex_anadido_es_critico():
    items = classify(prev_seo=seo(), curr_seo=seo(robots_directives=["follow", "noindex"]))
    assert "NOINDEX_ADDED" in codes(items)
    assert [i.severity for i in items if i.rule_code == "NOINDEX_ADDED"] == [CRITICAL]


def test_noindex_por_cabecera_tambien_es_critico():
    items = classify(
        prev_seo=seo(),
        curr_seo=seo(x_robots_tag="noindex", robots_directives=["follow", "index", "noindex"]),
    )
    assert "NOINDEX_ADDED" in codes(items)


def test_canonical_borrado_es_critico():
    items = classify(prev_seo=seo(), curr_seo=seo(canonical=None))
    assert "CANONICAL_REMOVED" in codes(items)
    assert max_severity(items) == CRITICAL


def test_canonical_que_pierde_la_autorreferencia():
    items = classify(
        prev_seo=seo(),
        curr_seo=seo(canonical="https://fitgeneration.es/otra-pagina"),
    )
    assert "CANONICAL_SELF_LOST" in codes(items)


def test_canonical_solo_cambia_la_barra_final_NO_es_cambio():
    """http→https o una barra de más no cambian el destino. Despertar a alguien
    por eso es justo el ruido que mata la herramienta."""
    items = classify(
        prev_seo=seo(canonical="https://fitgeneration.es/master"),
        curr_seo=seo(canonical="http://www.fitgeneration.es/master/"),
    )
    assert not [i for i in items if i.field == "canonical"]


def test_pagina_que_pasa_a_404_es_critico():
    items = classify(prev_seo=seo(), curr_seo=seo(status_code=404))
    assert "STATUS_ERROR" in codes(items)
    assert max_severity(items) == CRITICAL


def test_un_404_no_arrastra_una_cascada_de_falsos_cambios_seo():
    """Al caer, el HTML es el de una página de error: title distinto, sin H1,
    sin canonical. Reportar todo eso sería enterrar el problema real."""
    caida = {
        "status_code": 404, "final_url": BASE_SEO["final_url"],
        "title": "404 - Página no encontrada", "meta_description": "",
        "h1": [], "h2": [], "canonical": None, "meta_robots": "",
        "x_robots_tag": "", "robots_directives": [], "hreflang": [],
        "schema_types": [], "lang": "es", "word_count": 12,
    }
    items = classify(prev_seo=seo(), curr_seo=caida)
    assert codes(items) == ["STATUS_ERROR"]


def test_recuperarse_de_un_error_se_avisa():
    items = classify(prev_seo=seo(status_code=500), curr_seo=seo())
    assert "STATUS_RECOVERED" in codes(items)


def test_title_vacio_es_critico_pero_cambiado_es_warning():
    borrado = classify(prev_seo=seo(), curr_seo=seo(title=""))
    assert [i.severity for i in borrado if i.field == "title"] == [CRITICAL]

    cambiado = classify(prev_seo=seo(), curr_seo=seo(title="Otro título"))
    assert [i.severity for i in cambiado if i.field == "title"] == [WARNING]


def test_h1_desaparecido_es_critico():
    items = classify(prev_seo=seo(), curr_seo=seo(h1=[]))
    assert "H1_REMOVED" in codes(items)


def test_hreflang_perdido_es_critico():
    con = seo(hreflang=[{"lang": "es", "href": "https://fitgeneration.es/master"}])
    items = classify(prev_seo=con, curr_seo=seo(hreflang=[]))
    assert "HREFLANG_REMOVED" in codes(items)


# --------------------------------------------------------------------------
# Avisos e informativos
# --------------------------------------------------------------------------

def test_cambio_de_title_es_warning_y_lleva_antes_y_despues():
    items = classify(prev_seo=seo(), curr_seo=seo(title="Curso de Nutrición | Fit"))
    item = next(i for i in items if i.field == "title")
    assert item.rule_code == "TITLE_CHANGED"
    assert item.before_val == "Máster en Nutrición | Fit Generation"
    assert item.after_val == "Curso de Nutrición | Fit"


def test_schema_perdido_es_warning_y_anadido_es_info():
    perdido = classify(prev_seo=seo(), curr_seo=seo(schema_types=[]))
    assert [i.severity for i in perdido if i.field == "schema_types"] == [WARNING]

    anadido = classify(prev_seo=seo(), curr_seo=seo(schema_types=["Course", "FAQPage"]))
    assert [i.severity for i in anadido if i.field == "schema_types"] == [INFO]


def test_h2_cambiado_es_info_con_detalle():
    items = classify(prev_seo=seo(), curr_seo=seo(h2=["Temario", "Precio"]))
    item = next(i for i in items if i.field == "h2")
    assert item.severity == INFO
    assert item.detail["added"] == ["Precio"]
    assert item.detail["removed"] == ["Salidas profesionales"]


# --------------------------------------------------------------------------
# Contenido
# --------------------------------------------------------------------------

def test_reescritura_grande_es_warning_y_retoque_es_info():
    largo = " ".join(["palabra"] * 200)
    grande = classify(
        prev_seo=seo(word_count=200), curr_seo=seo(word_count=400),
        prev_text=largo, curr_text=largo + " " + " ".join(["nueva"] * 200),
    )
    assert "CONTENT_CHANGED_MAJOR" in codes(grande)

    pequeno = classify(
        prev_seo=seo(word_count=200), curr_seo=seo(word_count=201),
        prev_text=largo, curr_text=largo + " extra",
    )
    assert "CONTENT_CHANGED_MINOR" in codes(pequeno)


def test_el_diff_de_texto_lleva_hunks_legibles():
    items = classify(
        prev_seo=seo(), curr_seo=seo(),
        prev_text="El temario incluye anatomía. Las salidas son amplias.",
        curr_text="El temario incluye fisiología. Las salidas son amplias.",
    )
    item = next(i for i in items if i.kind == "content")
    hunks = item.detail["diff"]["hunks"]
    assert hunks
    assert any("anatomía" in " ".join(h["before"]) for h in hunks)


# --------------------------------------------------------------------------
# Enlaces
# --------------------------------------------------------------------------

def test_perder_muchos_enlaces_internos_es_warning():
    antes = {"internal": [f"https://x.com/{i}" for i in range(10)], "external": []}
    despues = {"internal": [f"https://x.com/{i}" for i in range(3)], "external": []}
    items = classify(
        prev_seo=seo(), curr_seo=seo(),
        prev_links=antes, curr_links=despues,
        watch_flags={"watch_links": True},
    )
    item = next(i for i in items if i.rule_code == "INTERNAL_LINKS_REMOVED")
    assert item.severity == WARNING
    assert item.detail["removed_count"] == 7


def test_los_enlaces_no_se_miran_si_el_watch_no_los_vigila():
    antes = {"internal": ["https://x.com/a"], "external": []}
    items = classify(
        prev_seo=seo(), curr_seo=seo(),
        prev_links=antes, curr_links={"internal": [], "external": []},
        watch_flags={"watch_links": False},
    )
    assert not [i for i in items if i.kind == "links"]


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def test_html_solo_se_reporta_si_no_hay_nada_mas():
    """Si cambió el title, decir además 'cambió el HTML' es redundante."""
    solo_html = classify(
        prev_seo=seo(), curr_seo=seo(), html_changed=True,
        watch_flags={"watch_html": True},
    )
    assert codes(solo_html) == ["HTML_CHANGED"]

    con_title = classify(
        prev_seo=seo(), curr_seo=seo(title="Otro"), html_changed=True,
        watch_flags={"watch_html": True},
    )
    assert "HTML_CHANGED" not in codes(con_title)


# --------------------------------------------------------------------------
# Severidad agregada
# --------------------------------------------------------------------------

def test_max_severity_se_queda_con_la_peor():
    items = classify(
        prev_seo=seo(),
        curr_seo=seo(title="Otro", robots_directives=["follow", "noindex"]),
    )
    assert max_severity(items) == CRITICAL


# --------------------------------------------------------------------------
# Digest: plurales
# --------------------------------------------------------------------------

def test_el_digest_concuerda_los_plurales():
    from backend.services.web.digest import DigestChange, build_digest

    uno = build_digest(
        client_name="Fit", date_label="22 jul",
        changes=[DigestChange(url="https://x.com/a", label=None, max_severity=WARNING,
                              items=[{"kind": "seo", "field": "title", "severity": WARNING,
                                      "rule_code": "TITLE_CHANGED",
                                      "before_val": "a", "after_val": "b"}])],
        urls_checked=1,
    )
    resumen = uno["blocks"][1]["elements"][0]["text"]
    assert "1 URL revisada" in resumen and "URLs revisadas" not in resumen
    assert "1 cambio " in resumen + " " and "1 cambios" not in resumen


def test_el_digest_devuelve_none_sin_cambios():
    from backend.services.web.digest import build_digest

    assert build_digest(client_name="Fit", date_label="22 jul",
                        changes=[], urls_checked=50) is None
