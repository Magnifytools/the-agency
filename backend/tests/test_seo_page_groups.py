"""Grupos de URL del Control SEO: validación, regex seguras, reparto (el primer
grupo que acepta la página gana) y cifras por grupo."""

import pytest

from backend.services import seo_control as sc


def _group(name, *rules):
    return {"name": name, "rules": [{"type": t, "value": v} for t, v in rules]}


# ── Regex ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pattern", [
    r"^/blog/\d{4}/",
    r"/(es|en)/producto",
    r"\.pdf$",
    r"/categoria/[a-z-]+/.*",
    r"^/p/\d+$",
])
def test_regex_admitidas(pattern):
    assert sc.regex_problem(pattern) is None


@pytest.mark.parametrize("pattern, fragment", [
    (r"(a+)+$", "anidadas"),
    (r"(.*)*", "anidadas"),
    (r"((ab)*c)+", "anidadas"),
    (r"(a|ab)*c", "alternativas"),
    (r"(\w+)-\1", "referencias"),
    (r"/(?=blog)", "lookarounds"),
    (r"(?<!x)/blog", "lookarounds"),
    (r".*a.*b.*c", "repeticiones sin tope"),
    (r"([a-", "no es una expresión regular válida"),
    ("x" * 201, "200"),
])
def test_regex_rechazadas(pattern, fragment):
    problem = sc.regex_problem(pattern)
    assert problem is not None and fragment in problem


# ── Validación ───────────────────────────────────────────────────────


def test_clean_page_groups_recorta_y_conserva_el_orden():
    raw = [
        {"name": "  Blog   de  marca ", "rules": [{"type": "prefix", "value": " /blog/ "}]},
        {"name": "Fichas", "rules": [{"type": "regex", "value": r"^/p/\d+$"}, {"type": "contains", "value": "producto"}]},
    ]
    assert sc.clean_page_groups(raw) == [
        _group("Blog de marca", ("prefix", "/blog/")),
        _group("Fichas", ("regex", r"^/p/\d+$"), ("contains", "producto")),
    ]
    assert sc.clean_page_groups(None) == []
    assert sc.clean_page_groups([]) == []


@pytest.mark.parametrize("groups", [
    "blog",
    [{"rules": [{"type": "prefix", "value": "/x"}]}],
    [_group("", ("prefix", "/x"))],
    [_group("x" * 61, ("prefix", "/x"))],
    [_group("Sin grupo", ("prefix", "/x"))],
    [_group("Blog", ("prefix", "/blog")), _group("BLOG", ("prefix", "/b"))],
    [{"name": "Blog", "rules": []}],
    [_group("Blog", ("starts", "/blog"))],
    [_group("Blog", ("prefix", "   "))],
    [_group("Blog", ("prefix", "x" * 201))],
    [_group("Blog", ("regex", "(a+)+"))],
    [_group("Blog", *[("prefix", f"/{i}") for i in range(21)])],
    [_group(f"G{i}", ("prefix", f"/{i}")) for i in range(31)],
])
def test_clean_page_groups_rechaza(groups):
    with pytest.raises(ValueError):
        sc.clean_page_groups(groups)


def test_admite_30_grupos_de_20_reglas():
    groups = [_group(f"G{i}", *[("prefix", f"/{i}/{j}") for j in range(20)]) for i in range(30)]
    assert len(sc.clean_page_groups(groups)) == 30


# ── Reparto ──────────────────────────────────────────────────────────


def test_page_path_como_las_secciones():
    assert sc.page_path("https://acme.com/Blog/Ca%C3%B1a?x=1", "sc-domain:acme.com") == "/blog/caña?x=1"
    assert sc.page_path("https://acme.com/es/blog/a", "https://acme.com/es/") == "/blog/a"
    assert sc.page_path("https://acme.com", "sc-domain:acme.com") == "/"


def test_gana_el_primer_grupo_que_acepta_la_pagina():
    matcher = sc.PageGroupMatcher([
        _group("Guías", ("prefix", "/blog/guias/")),
        _group("Blog", ("prefix", "blog/")),          # sin barra inicial: se le pone
        _group("Tienda", ("contains", "tienda.acme.com"), ("regex", r"^/p/\d+$")),
        _group("Repetido", ("prefix", "/blog/")),     # nunca gana: Blog va antes
    ], "sc-domain:acme.com")
    assert matcher("https://acme.com/blog/guias/zapatos") == "Guías"
    assert matcher("https://acme.com/BLOG/otra") == "Blog"
    assert matcher("https://tienda.acme.com/cualquier") == "Tienda"
    assert matcher("https://acme.com/p/123") == "Tienda"
    assert matcher("https://acme.com/p/123/fotos") == sc.UNGROUPED
    assert matcher("https://acme.com/") == sc.UNGROUPED
    assert matcher.names == ["Guías", "Blog", "Tienda", "Repetido"]


def test_prefijo_con_url_entera_compara_la_url():
    matcher = sc.PageGroupMatcher([_group("Blog www", ("prefix", "https://www.acme.com/blog"))], "sc-domain:acme.com")
    assert matcher("https://www.acme.com/blog/a") == "Blog www"
    assert matcher("https://acme.com/blog/a") == sc.UNGROUPED


def test_regla_rota_guardada_no_acepta_nada():
    matcher = sc.PageGroupMatcher([{"name": "Rota", "rules": [{"type": "regex", "value": "(a+)+"}]}], None)
    assert matcher("https://acme.com/aaaa") == sc.UNGROUPED


def test_el_reparto_tiene_tope_de_tiempo():
    matcher = sc.PageGroupMatcher([_group("Blog", ("prefix", "/blog/"))], None)
    with pytest.raises(sc.PageGroupTimeout):
        matcher.assign([f"https://a.com/{i}" for i in range(500)], budget_seconds=-1)


def test_cifras_por_grupo_suman_y_ponderan():
    pages = {
        "https://acme.com/blog/a": sc.Agg(10, 100, 200.0, 5, 50, 250.0),   # pos 2 ← 5
        "https://acme.com/blog/b": sc.Agg(30, 300, 1200.0, 0, 0, 0.0),     # pos 4, nueva
        "https://acme.com/p/1": sc.Agg(20, 200, 600.0, 20, 100, 300.0),
        "https://acme.com/contacto": sc.Agg(0, 0, 0.0, 3, 30, 90.0),       # sólo antes
    }
    matcher = sc.PageGroupMatcher([
        _group("Blog", ("prefix", "/blog/")),
        _group("Vacío", ("prefix", "/nada/")),
        _group("Fichas", ("regex", r"^/p/\d+$")),
    ], "sc-domain:acme.com")
    rows = {r["key"]: r for r in sc.group_rows(pages, matcher)}
    assert list(rows) == ["Blog", "Vacío", "Fichas", sc.UNGROUPED]
    blog = rows["Blog"]
    assert (blog["clicks"], blog["previous_clicks"], blog["impressions"], blog["pages"]) == (40, 5, 400, 2)
    assert blog["position"] == pytest.approx(1400 / 400)
    assert blog["position_delta"] == pytest.approx(round(5.0 - 3.5, 2))
    assert blog["clicks_share"] == pytest.approx(round(40 / 60, 4))
    assert rows["Vacío"]["clicks"] == 0 and rows["Vacío"]["pages"] == 0 and rows["Vacío"]["position"] is None
    assert rows[sc.UNGROUPED]["pages"] == 0 and rows[sc.UNGROUPED]["previous_clicks"] == 3


def test_sin_grupos_todo_va_a_sin_grupo():
    pages = {"https://acme.com/a": sc.Agg(1, 10, 10.0, 0, 0, 0.0)}
    rows = sc.group_rows(pages, sc.PageGroupMatcher([], None))
    assert [r["key"] for r in rows] == [sc.UNGROUPED] and rows[0]["clicks_share"] == 1.0
