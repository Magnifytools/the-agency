"""Control SEO: reglas puras (marca, secciones, movimientos, posición)."""
from datetime import date

import pytest

from backend.services import seo_control as sc


# ── Marca ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("Peluquería  CANINA", "peluqueria canina"),
    ("Fit-Generation.com", "fit generation com"),
    ("  ÀÉÎõü ñ  ", "aeiou n"),
    ("Straße", "strasse"),
    ("", ""),
])
def test_normalize(raw, expected):
    assert sc.normalize(raw) == expected


@pytest.mark.parametrize("query, expected", [
    ("fit generation horarios", True),
    ("FITGENERATION opiniones", True),      # sin espacios en la consulta
    ("fit-generation.com", True),           # puntuación → espacio
    ("Fít Generatión", True),               # acentos y mayúsculas
    ("gimnasio barcelona", False),
    ("fit gen", False),                     # subcadena del término, no al revés
])
def test_is_brand_con_y_sin_espacios(query, expected):
    assert sc.is_brand(query, ["Fit Generation"]) is expected


def test_is_brand_sin_terminos_o_con_terminos_cortos():
    assert sc.is_brand("acme", []) is False
    # Un término de menos de 3 letras/números no clasifica nada (evita falsos positivos).
    assert sc.is_brand("seo para ab", ["ab"]) is False
    assert sc.is_brand("abc tienda", ["a-b-c"]) is True


def test_is_brand_no_usa_regex():
    assert sc.is_brand("precio c++ curso", ["c++ curso"]) is True   # → "c curso"
    assert sc.is_brand("cualquier cosa", [".*"]) is False


def test_clean_brand_terms_recorta_y_quita_duplicados_normalizados():
    assert sc.clean_brand_terms(["  Acme  Corp ", "acme corp", "ACMECORP", "Ácme corp", "otra"]) == [
        "Acme Corp", "otra",
    ]
    assert sc.clean_brand_terms(None) == []
    assert sc.clean_brand_terms(["", "   "]) == []


@pytest.mark.parametrize("terms", [
    ["ab"],
    ["x" * 61],
    ["- -"],                      # 3 caracteres pero ninguna letra
    [f"marca{i}" for i in range(21)],
    [123],
])
def test_clean_brand_terms_rechaza(terms):
    with pytest.raises(ValueError):
        sc.clean_brand_terms(terms)


def test_clean_brand_terms_admite_20_y_60_caracteres():
    assert len(sc.clean_brand_terms([f"marca{i}" for i in range(20)])) == 20
    assert sc.clean_brand_terms(["x" * 60]) == ["x" * 60]


# ── Secciones ────────────────────────────────────────────────────────


@pytest.mark.parametrize("page, site, expected", [
    ("https://acme.com/", "sc-domain:acme.com", ("/", "Inicio")),
    ("https://acme.com", "sc-domain:acme.com", ("/", "Inicio")),
    ("https://acme.com/?utm=1#top", "sc-domain:acme.com", ("/", "Inicio")),
    ("https://www.acme.com/Blog/post-1?x=1", "sc-domain:acme.com", ("/blog", "/blog")),
    ("https://acme.com/blog/", "sc-domain:acme.com", ("/blog", "/blog")),
    ("https://acme.com/contacto.html", "sc-domain:acme.com", ("/contacto.html", "/contacto.html")),
    ("https://acme.com/categor%C3%ADa/x", "sc-domain:acme.com", ("/categoría", "/categoría")),
    ("https://tienda.acme.com/producto/1", "sc-domain:acme.com", ("tienda.acme.com", "tienda.acme.com")),
    ("https://acme.com/es/servicios/seo", "https://acme.com/es/", ("/servicios", "/servicios")),
    ("https://acme.com/es/", "https://acme.com/es/", ("/", "Inicio")),
    ("https://acme.com/blog/x", "https://acme.com/", ("/blog", "/blog")),
])
def test_section_of(page, site, expected):
    assert sc.section_of(page, site) == expected


# ── Ventana ──────────────────────────────────────────────────────────


def test_seo_window_28_y_7():
    w = sc.seo_window(date(2026, 10, 18))
    assert (w.start, w.end, w.previous_start, w.previous_end, w.days) == (
        date(2026, 9, 21), date(2026, 10, 18), date(2026, 8, 24), date(2026, 9, 20), 28,
    )
    w7 = sc.seo_window(date(2026, 10, 18), 7)
    assert (w7.start, w7.previous_start, w7.previous_end) == (date(2026, 10, 12), date(2026, 10, 5), date(2026, 10, 11))


# ── Cifras ───────────────────────────────────────────────────────────


def test_posicion_ponderada_por_impresiones():
    # Día A: pos 2 con 900 impresiones; día B: pos 20 con 100 → 3,8 (no 11).
    agg = sc.Agg(impressions=1000, weighted=2 * 900 + 20 * 100)
    assert sc.weighted_position(agg.weighted, agg.impressions) == pytest.approx(3.8)
    assert sc.weighted_position(0.0, 0) is None


def test_position_delta_positivo_es_mejora():
    assert sc.position_delta(8.0, 5.0) == 3.0
    assert sc.position_delta(5.0, 8.0) == -3.0
    assert sc.position_delta(None, 5.0) is None


def test_sin_clasificar_nunca_negativo():
    assert sc.unclassified(100, 80) == 20
    assert sc.unclassified(100, 130) == 0


@pytest.mark.parametrize("impressions, previous, state", [
    (50, 0, "new"), (0, 50, "lost"), (50, 40, "both"), (0, 0, "both"),
])
def test_mover_state(impressions, previous, state):
    assert sc.mover_state(impressions, previous) == state


def _row(key, clicks, prev_clicks, impressions, prev_impressions, pos=5.0, prev_pos=5.0):
    agg = sc.Agg(clicks, impressions, pos * impressions, prev_clicks, prev_impressions, prev_pos * prev_impressions)
    return {"key": key, **sc.mover_row(agg)}


def test_movers_por_clics_umbral_en_la_ventana_mayor():
    rows = [
        _row("nueva", 10, 0, 40, 0),       # nueva, 40 impresiones ahora
        _row("perdida", 0, 12, 0, 35),     # perdida, 35 antes
        _row("poca", 5, 0, 10, 0),         # no llega al mínimo
        _row("sube", 30, 10, 300, 200),
        _row("baja", 2, 20, 100, 200),
    ]
    gain = sc.select_movers(rows, "clicks_gain")
    assert [r["key"] for r in gain] == ["sube", "nueva"]
    assert gain[1]["state"] == "new" and gain[1]["clicks_pct"] is None
    loss = sc.select_movers(rows, "clicks_loss")
    assert [r["key"] for r in loss] == ["baja", "perdida"]
    assert loss[1]["state"] == "lost" and loss[1]["position"] is None
    assert [r["key"] for r in sc.select_movers(rows, "clicks_gain", min_impressions=0)] == ["sube", "nueva", "poca"]


def test_movers_por_posicion_piden_el_minimo_en_las_dos_ventanas():
    rows = [
        _row("mejora", 5, 5, 100, 100, pos=3.0, prev_pos=9.0),
        _row("empeora", 5, 5, 100, 100, pos=12.0, prev_pos=4.0),
        _row("nueva", 5, 0, 100, 0, pos=2.0),
        _row("escasa", 5, 5, 100, 10, pos=2.0, prev_pos=40.0),
    ]
    assert [(r["key"], r["position_delta"]) for r in sc.select_movers(rows, "position_gain")] == [("mejora", 6.0)]
    assert [(r["key"], r["position_delta"]) for r in sc.select_movers(rows, "position_loss")] == [("empeora", -8.0)]


def test_bloque_de_totales():
    agg = sc.Agg(clicks=110, impressions=1000, weighted=4.0 * 1000, prev_clicks=100, prev_impressions=1000,
                 prev_weighted=5.0 * 1000)
    block = sc._totals_block(agg)
    assert block["current"] == {"clicks": 110, "impressions": 1000, "ctr": 0.11, "position": 4.0}
    assert block["change"] == {"clicks_pct": 10.0, "impressions_pct": 0.0, "ctr_delta": 0.01, "position_delta": 1.0}


def test_reparto_de_marca_y_sin_clasificar():
    totals = sc.Agg(clicks=100, impressions=1000, prev_clicks=50, prev_impressions=400)
    queries = {
        "acme zapatos": sc.Agg(clicks=40, impressions=300, prev_clicks=30, prev_impressions=200),
        "zapatos baratos": sc.Agg(clicks=30, impressions=500, prev_clicks=40, prev_impressions=300),
    }
    current, previous = sc._brand_split(totals, queries, sc.BrandMatcher(["Acme"]))
    assert current == {
        "brand": {"clicks": 40, "impressions": 300},
        "non_brand": {"clicks": 30, "impressions": 500},
        "unclassified": {"clicks": 30, "impressions": 200},
    }
    # Antes, la suma de consultas pasaba del total (redondeos de Google): 0, no negativo.
    assert previous["unclassified"] == {"clicks": 0, "impressions": 0}


def test_secciones_reparten_por_clics():
    pages = {
        "https://acme.com/blog/a": sc.Agg(clicks=30, impressions=300, weighted=3.0 * 300, prev_clicks=10,
                                          prev_impressions=100, prev_weighted=6.0 * 100),
        "https://acme.com/blog/b": sc.Agg(clicks=10, impressions=100, weighted=7.0 * 100),
        "https://acme.com/": sc.Agg(clicks=60, impressions=900, weighted=1.0 * 900, prev_clicks=60,
                                    prev_impressions=900, prev_weighted=1.0 * 900),
    }
    sections = sc._sections(pages, "sc-domain:acme.com")
    assert [s["key"] for s in sections] == ["/", "/blog"]
    blog = sections[1]
    assert blog["clicks"] == 40 and blog["clicks_share"] == 0.4 and blog["pages"] == 2
    assert blog["position"] == 4.0 and blog["position_delta"] == 2.0
    assert blog["clicks_pct"] == 300.0


def test_tendencia_16_semanas_ancladas_en_el_final():
    end = date(2026, 10, 18)
    trend = sc._trend(end, [("acme", 0, 5), ("zapatos", 0, 3), ("acme", 15, 1)], {0: 10, 15: 1},
                      sc.BrandMatcher(["acme"]))
    assert len(trend) == 16
    assert trend[-1] == {"week_start": "2026-10-12", "week_end": "2026-10-18", "brand_clicks": 5,
                         "non_brand_clicks": 3, "unclassified_clicks": 2}
    assert trend[0]["week_end"] == "2026-07-05" and trend[0]["brand_clicks"] == 1
