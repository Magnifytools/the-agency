"""PDF del resumen: mismo contenido que el email, A4, sin red."""
from __future__ import annotations

import asyncio
import re
import socket
import time
import urllib.request
import zlib
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.schemas.digest import DigestContent
from backend.services import digest_pdf

SEO = {
    "status": "ok", "site_url": "sc-domain:ejemplo.com",
    "month": {"start": "2026-09-01", "end": "2026-09-30", "days": 30, "clicks": 1234,
              "impressions": 56789, "ctr": 2.17, "position": 12.3},
    "previous": {"start": "2026-08-01", "end": "2026-08-31", "days": 31, "clicks": 1000,
                 "impressions": 50000, "ctr": 2.0, "position": 13.1},
    "year_ago": None,
    "vs_previous": {"clicks_pct": 23.4, "impressions_pct": 13.6, "ctr_delta": 0.17, "position_delta": 0.8},
    "vs_year_ago": None,
}
GA4 = {
    "status": "ok",
    "month": {"start": "2026-09-01", "sessions": 4321, "key_events": 87, "ai_sessions": 54},
    "previous": {"start": "2026-08-01", "sessions": 4000, "key_events": 90, "ai_sessions": 30},
    "vs_previous": {"sessions_pct": 8.0, "key_events_pct": -3.3, "ai_sessions_pct": 80.0},
}


def _content(**overrides) -> DigestContent:
    data = {
        "greeting": "Hola Marta, aquí tienes el resumen de septiembre.",
        "sections": {
            "done": [{"title": "Fichas de categoría optimizadas", "description": "Títulos y H1 de 40 URLs 🚀"}],
            "need": [{"title": "Acceso a Analytics", "description": "Para medir conversiones"}],
            "next": [{"title": "Auditoría de enlazado", "description": "En octubre"}],
        },
        "closing": 'Seguimiento en <a href="https://docs.google.com/x">esta hoja</a>.\n<b>David</b>',
    }
    data.update(overrides)
    return DigestContent(**data)


def _text(pdf: bytes) -> str:
    """Texto de los flujos de contenido (fpdf2 los comprime con zlib)."""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            chunks.append(zlib.decompress(match.group(1)).decode("cp1252", "replace"))
        except zlib.error:
            continue
    return "\n".join(chunks)


def _render(content: DigestContent | None = None, **kwargs) -> bytes:
    return digest_pdf.render_pdf(content or _content(), client_name="Fit Generation",
                                 period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                                 **{"seo": SEO, "ga4": GA4, **kwargs})


def test_produces_a_real_pdf_with_the_client_and_the_email_content():
    pdf = _render()
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 2000
    text = _text(pdf)
    for expected in ("Fit Generation", "Hola Marta", "Fichas de categor", "Acceso a Analytics",
                     "Auditor", "Visibilidad en Google", "Visitas y conversiones", "1.234", "+23,4 %",
                     "esta hoja", "David", "PER"):
        assert expected in text, expected


def test_switches_remove_the_seo_and_ga4_blocks_like_in_the_email():
    without_seo = _text(_render(_content(include_seo=False)))
    assert "Visibilidad en Google" not in without_seo and "Visitas y conversiones" in without_seo
    without_ga4 = _text(_render(_content(include_ga4=False)))
    assert "Visitas y conversiones" not in without_ga4 and "Visibilidad en Google" in without_ga4
    # Sin datos "ok" no hay bloque aunque el interruptor esté encendido.
    no_data = _text(_render(seo={"status": "incomplete"}, ga4=None))
    assert "Visibilidad en Google" not in no_data and "Visitas y conversiones" not in no_data


def test_rendering_never_touches_the_network(monkeypatch):
    calls = []

    def blocked(*args, **kwargs):
        calls.append(args)
        raise AssertionError("el PDF no debe abrir conexiones")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    # fpdf2 >= 2.8.8 descarga con build_opener (antes, urlopen).
    monkeypatch.setattr("fpdf.image_parsing.build_opener", blocked)
    closing = ('<img src="http://169.254.169.254/latest/meta-data">'
               '<a href="javascript:alert(1)">mal</a> <a href="https://ok.example">bien</a>'
               '<style>@import url(http://evil.example/x.css)</style><script>fetch("http://x")</script>')
    pdf = _render(_content(closing=closing))
    assert pdf.startswith(b"%PDF-") and calls == []
    text = _text(pdf)
    assert "evil.example" not in text and "fetch" not in text
    assert b"javascript:" not in pdf and b"https://ok.example" in pdf


def test_the_pdf_engine_refuses_any_image():
    pdf = digest_pdf._OfflinePDF("x")
    pdf.add_page()
    with pytest.raises(RuntimeError):
        pdf.image("http://169.254.169.254/latest")


def test_closing_keeps_breaks_bold_and_only_safe_links():
    runs = digest_pdf.closing_runs('Hola<br>uno\n<strong>dos</strong> <a href="mailto:a@b.c">mail</a>'
                                   '<a href="ftp://x">ftp</a>')
    assert ("dos", True, "") in runs
    assert ("mail", False, "mailto:a@b.c") in runs
    assert ("ftp", False, "") in runs
    assert "".join(text for text, _b, _l in runs).startswith("Hola\nuno\n")


def test_clean_text_drops_what_helvetica_cannot_print():
    assert digest_pdf.clean_text("Listo 🚀 — «sí» € → fin") == "Listo — «sí» € -> fin"


@pytest.mark.parametrize("name, start, end, expected", [
    ("Zapaterías Muñoz S.L.", date(2026, 9, 1), date(2026, 9, 30), "informe-zapaterias-munoz-s-l-2026-09.pdf"),
    ("Fit", date(2026, 9, 7), date(2026, 9, 13), "informe-fit-2026-09-07_2026-09-13.pdf"),
    ("", None, None, "informe-cliente-42.pdf"),
    ('a"b\r\nc', date(2026, 2, 1), date(2026, 2, 28), "informe-a-b-c-2026-02.pdf"),
])
def test_filename(name, start, end, expected):
    assert digest_pdf.pdf_filename(name, start, end, 42) == expected


def test_long_digests_paginate():
    items = [{"title": f"Tarea {i}", "description": "Detalle " * 40} for i in range(40)]
    pdf = _render(_content(sections={"done": items}))
    assert len(re.findall(rb"/Type /Page\b", pdf)) > 2


def _digest(**overrides):
    data = {"id": 7, "content": _content().model_dump(), "raw_context": {"seo": SEO, "ga4": GA4},
            "tone": None, "period_start": date(2026, 9, 1), "period_end": date(2026, 9, 30)}
    data.update(overrides)
    return SimpleNamespace(**data)


async def test_digest_pdf_runs_off_the_event_loop_and_names_the_file():
    data, filename = await digest_pdf.digest_pdf(_digest(), "Fit Generation")
    assert data.startswith(b"%PDF-") and filename == "informe-fit-generation-2026-09.pdf"


async def test_slow_render_becomes_504(monkeypatch):
    from backend.api.routes.digests import build_pdf_or_error

    monkeypatch.setattr(digest_pdf, "PDF_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(digest_pdf, "render_pdf", lambda *a, **k: time.sleep(0.3) or b"")
    with pytest.raises(HTTPException) as exc:
        await build_pdf_or_error(_digest(), "x")
    assert exc.value.status_code == 504
    await asyncio.sleep(0.3)  # deja terminar el hilo antes de cerrar el bucle


async def test_digest_without_content_is_400():
    from backend.api.routes.digests import build_pdf_or_error

    with pytest.raises(HTTPException) as exc:
        await build_pdf_or_error(_digest(content=None), "x")
    assert exc.value.status_code == 400
