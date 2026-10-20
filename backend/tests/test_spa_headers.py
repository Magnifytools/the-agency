"""Cabeceras de las páginas públicas que sirve el SPA (backend/main.py)."""
from backend.main import spa_headers


def test_paginas_legales_publicas_no_se_indexan():
    for path in ("acerca", "privacidad", "privacidad/"):
        headers = spa_headers(path)
        assert "noindex" in headers["X-Robots-Tag"]
        assert "Referrer-Policy" not in headers


def test_enlace_del_cliente_sigue_sin_referer():
    headers = spa_headers("c/tok_123")
    assert "noindex" in headers["X-Robots-Tag"]
    assert headers["Referrer-Policy"] == "no-referrer"


def test_el_resto_de_la_app_no_cambia():
    assert spa_headers("") == {}
    assert spa_headers("clients/22") == {}
    assert spa_headers("acerca-de-otra-cosa") == {}
