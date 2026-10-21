"""Vigilancia de cambios (Webs fase 2a): piezas puras, sin base de datos ni red.

Portado de Vigil: tests/test_html_diff.py (troceado y diff), test_lista_cambios.py
(tamaño del cambio de maquetación en Slack), test_barrido_manual.py
(calendario) y test_cron.py (el equivalente aquí es la puerta del job y la hora
local). Lo que necesita Postgres está en tests/integration/test_web_changes.py.
"""
from __future__ import annotations

import asyncio
import gzip
import uuid
from datetime import UTC, date, datetime, time

import pytest

from backend.services.web import capture_defaults as defaults
from backend.services.web import sweep
from backend.services.web.calendario import festivos_nacionales, toca_barrido
from backend.services.web.classifier import WARNING, classify
from backend.services.web.digest import DigestChange, _describe, build_digest, build_summary
from backend.services.web.extractor import extract
from backend.services.web.html_diff import delta_stats, diff_html, lineas
from backend.services.web.safe_http import FetchResult


# ── html_diff (de Vigil: test_html_diff.py) ──────────────────────────


def test_el_html_normalizado_se_parte_en_una_etiqueta_por_linea():
    assert lineas("<div><p>Hola</p><span>Adiós</span></div>") == ["<div>", "<p>Hola</p>", "<span>Adiós</span>", "</div>"]


def test_html_vacio_no_revienta():
    assert lineas("") == []
    assert diff_html("", "")["hunks"] == []


ANTES = "<div><h2>Temario</h2><p>Anatomía aplicada.</p><a href='/x'>Ver</a></div>"
DESPUES = "<div><h2>Programa</h2><p>Anatomía aplicada.</p><a href='/x'>Ver</a></div>"


def test_solo_sale_el_trozo_que_cambia_y_su_contexto():
    d = diff_html(ANTES, DESPUES)
    assert d["stats"]["added"] == 1 and d["stats"]["removed"] == 1 and d["hunks_total"] == 1
    filas = d["hunks"][0]["lines"]
    assert [f["s"] for f in filas if f["t"] == "-"] == ["<h2>Temario</h2>"]
    assert [f["s"] for f in filas if f["t"] == "+"] == ["<h2>Programa</h2>"]
    assert any(f["t"] == " " and f["s"] == "<div>" for f in filas)


def test_dos_cambios_lejanos_salen_como_dos_zonas():
    a = "<div>" + "".join(f"<p>línea {i}</p>" for i in range(40)) + "</div>"
    b = a.replace("<p>línea 0</p>", "<p>línea CERO</p>").replace("<p>línea 39</p>", "<p>línea TREINTA Y NUEVE</p>")
    d = diff_html(a, b)
    assert d["hunks_total"] == 2 and d["truncated"] is False


def test_una_pagina_desmesurada_lo_dice_en_vez_de_colgarse():
    enorme = "".join(f"<p>{i}</p>" for i in range(40_000))
    d = diff_html(enorme, enorme + "<p>fin</p>")
    assert d["too_big"] is True and d["hunks"] == []


def test_sin_html_anterior_no_se_inventa_un_cero():
    """``delta_stats`` devuelve None cuando no hay con qué comparar: un 0 se
    leería como "no cambió nada"."""
    assert delta_stats("", "<p>algo</p>") is None
    assert delta_stats("<p>algo</p>", "") is None
    items = classify(prev_seo={"status_code": 200, "title": "T"}, curr_seo={"status_code": 200, "title": "T"},
                     html_changed=True, html_delta=None, watch_flags={"watch_seo": True, "watch_html": True})
    assert [i.rule_code for i in items] == ["HTML_CHANGED"] and items[0].detail == {}


# ── Digest de Slack ──────────────────────────────────────────────────


def _change(**kw):
    item = {"kind": "seo", "field": "title", "severity": WARNING, "rule_code": "TITLE_CHANGED",
            "before_val": "a", "after_val": "b"}
    return DigestChange(url="https://x.com/a", label=None, max_severity=WARNING, items=[item], **kw)


def test_el_digest_concuerda_los_plurales_y_enlaza_cada_cambio_a_the_agency():
    change_id = str(uuid.uuid4())
    uno = build_digest("Fit", "22 jul 2026", [_change(change_id=change_id)], urls_checked=1,
                       detail_url="https://agency.magnifytools.com/web/cambios?cliente=1")
    resumen = uno["blocks"][1]["elements"][0]["text"]
    assert "1 URL revisada" in resumen and "URLs revisadas" not in resumen
    assert "1 cambios" not in resumen
    texto = str(uno["blocks"])
    assert f"https://agency.magnifytools.com/web/cambios/{change_id}" in texto
    assert "Ver el detalle en The Agency" in texto and "Vigil" not in texto
    assert uno["blocks"][0]["text"]["text"].startswith("Cambios en la web · Fit")


def test_el_digest_devuelve_none_sin_cambios():
    assert build_digest("Fit", "22 jul", [], urls_checked=50) is None


def test_slack_dice_el_mismo_tamano_que_la_pantalla():
    texto = _describe({"rule_code": "HTML_CHANGED", "field": "raw_html", "before_val": None, "after_val": None,
                       "detail": {"added": 14, "removed": 9, "after_lines": 3837}})
    assert "+14" in texto and "−9" in texto and "3837" in texto
    assert _describe({"rule_code": "HTML_CHANGED", "field": "raw_html", "before_val": None, "after_val": None,
                      "detail": {}}) == "*cambió el HTML*"


def test_lo_que_no_se_pudo_mirar_sale_en_el_digest_y_en_el_resumen():
    nota = "fit.es: no se han podido mirar 5 de 6 páginas. Probable bloqueo (WAF/anti-bots), no páginas caídas."
    digest = build_digest("Fit", "1 oct", [_change()], urls_checked=6, errors=5, notes=[nota])
    summary = build_summary("Fit", "1 oct", urls_checked=6, urls_changed=0, n_critical=0, errors=5,
                            trigger="scheduler", notes=[nota])
    assert "Probable bloqueo" in str(digest["blocks"]) and "Probable bloqueo" in str(summary["blocks"])
    assert "ninguna con cambios" in summary["text"] and summary["text"].startswith("Webs · Fit")


# ── Calendario (de Vigil: test_barrido_manual.py) ────────────────────


def test_por_defecto_no_se_barre_en_fin_de_semana():
    cfg = sweep.SweepSettings().calendar()
    assert toca_barrido(cfg, date(2026, 7, 23))[0] is True    # jueves
    assert toca_barrido(cfg, date(2026, 7, 25))[0] is False   # sábado
    assert toca_barrido(cfg, date(2026, 7, 26))[0] is False   # domingo


def test_el_motivo_de_no_barrer_es_legible():
    assert "sábado" in toca_barrido({"sweep_weekdays": [1, 2, 3, 4, 5]}, date(2026, 7, 25))[1]


def test_se_saltan_los_festivos_marcados():
    toca, motivo = toca_barrido({"sweep_weekdays": [1, 2, 3, 4, 5], "sweep_skip_dates": ["2026-12-25"]},
                                date(2026, 12, 25))
    assert toca is False and "festivo" in motivo


def test_config_rota_no_deja_de_barrer():
    """JSONB ya decodificado o texto: un valor corrupto cae al defecto, no apaga la vigilancia."""
    assert toca_barrido({"sweep_weekdays": "{esto no es json", "sweep_skip_dates": "???"}, date(2026, 7, 23))[0]
    assert toca_barrido({"sweep_weekdays": {"no": "lista"}, "sweep_skip_dates": None}, date(2026, 7, 23))[0]


def test_festivos_nacionales_calcula_viernes_santo():
    festivos = festivos_nacionales(2026)
    assert "2026-04-03" in festivos and "2026-12-25" in festivos and "2026-01-01" in festivos


# ── Defaults en código, no en columnas ───────────────────────────────


def test_los_defaults_no_traen_selectores_que_se_coman_contenido():
    """``[aria-live]`` y ``.carousel`` ya cegaron una vez (lección 0quater de Vigil)."""
    assert "[aria-live]" not in defaults.DEFAULT_IGNORE_SELECTORS
    assert ".carousel" not in defaults.DEFAULT_IGNORE_SELECTORS


class _Web:
    """Fila de ``client_web_settings`` de mentira."""

    def __init__(self, **kw):
        base = dict(default_content_selector=None, default_ignore_selectors=None, default_ignore_regexes=None,
                    max_concurrency=None, request_timeout_s=None, crawl_delay_ms=None, user_agent=None,
                    digest_min_severity=None, sweep_weekdays=None, sweep_skip_dates=None,
                    sweep_summary_to_slack=None, slack_webhook_url=None, slack_enabled=False, slack_revoked_at=None)
        base.update(kw)
        self.__dict__.update(base)


def test_null_es_el_default_del_codigo_y_una_lista_guardada_manda_aunque_este_vacia():
    assert sweep.effective_settings(None) == sweep.effective_settings(_Web())
    cfg = sweep.effective_settings(_Web())
    assert cfg.ignore_selectors == defaults.DEFAULT_IGNORE_SELECTORS
    assert cfg.max_concurrency == 6 and cfg.request_timeout_s == 20 and cfg.crawl_delay_ms == 300
    assert cfg.sweep_weekdays == (1, 2, 3, 4, 5) and cfg.sweep_summary_to_slack is True
    vacio = sweep.effective_settings(_Web(default_ignore_selectors=[], crawl_delay_ms=0, sweep_weekdays=[6, 7],
                                          sweep_summary_to_slack=False, digest_min_severity="critical"))
    assert vacio.ignore_selectors == () and vacio.crawl_delay_ms == 0 and vacio.sweep_weekdays == (6, 7)
    assert vacio.sweep_summary_to_slack is False and vacio.digest_min_severity == "critical"


def test_la_url_pisa_al_cliente_y_null_o_vacio_hereda():
    cfg = sweep.effective_settings(_Web(default_ignore_selectors=["nav"], default_content_selector="main"))
    watch = type("W", (), {"content_selector": None, "ignore_selectors": None, "ignore_regexes": []})()
    resolved = sweep.effective_config(watch, cfg)
    assert resolved.ignore_selectors == ("nav",) and resolved.content_selector == "main"
    assert resolved.ignore_regexes == defaults.DEFAULT_IGNORE_REGEXES
    watch.ignore_selectors, watch.content_selector = [".x"], ".card"
    resolved = sweep.effective_config(watch, cfg)
    assert resolved.ignore_selectors == (".x",) and resolved.content_selector == ".card"


def test_el_estado_de_slack_sale_de_la_configuracion():
    assert sweep.slack_state(None) == "disabled"
    assert sweep.slack_state(_Web(slack_webhook_url="v1:x", slack_enabled=True)) == "ready"
    assert sweep.slack_state(_Web(slack_webhook_url="v1:x", slack_enabled=False)) == "disabled"
    assert sweep.slack_state(_Web(slack_webhook_url="v1:x", slack_enabled=False,
                                  slack_revoked_at=datetime.now(UTC))) == "revoked"


# ── El job: apagado por defecto y a su hora (equivalente de test_cron.py) ──


def test_el_job_web_sweep_esta_apagado_por_defecto_con_su_lock(monkeypatch):
    from backend.config import settings
    from backend.services.job_catalog import job_definitions

    monkeypatch.setattr(settings, "WEB_SWEEP_ENABLED", False)
    definitions = {d.spec.key: d for d in job_definitions()}
    job = definitions["web_sweep"]
    assert not job.enabled and "WEB_SWEEP_ENABLED" in job.paused_reason
    assert (job.spec.lock_id, job.spec.interval_seconds, job.spec.timeout_seconds, job.spec.retry_seconds) == (
        16, 60, 900, 300)
    locks = [d.spec.lock_id for d in definitions.values()]
    assert len(locks) == len(set(locks)), "dos jobs no pueden compartir advisory lock"
    monkeypatch.setattr(settings, "WEB_SWEEP_ENABLED", True)
    assert {d.spec.key: d for d in job_definitions()}["web_sweep"].enabled


def test_la_hora_del_barrido_es_local_y_una_mal_escrita_no_lo_apaga(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "WEB_SWEEP_LOCAL_TIME", "07:15")
    assert sweep.sweep_start_time() == time(7, 15)
    monkeypatch.setattr(settings, "WEB_SWEEP_LOCAL_TIME", "siete")
    assert sweep.sweep_start_time() == time(6, 30)
    # 04:30 UTC del 21-oct es 06:30 en Madrid (verano): la fecha y la hora son las locales.
    assert sweep.local_date(datetime(2026, 10, 21, 23, 30, tzinfo=UTC)) == date(2026, 10, 22)


@pytest.mark.asyncio
async def test_el_ciclo_del_job_falla_parcial_si_un_cliente_falla(monkeypatch):
    from backend.services.job_runtime import JobFailure
    from backend.startup import background_tasks

    async def fake_cycle(_factory):
        return sweep.CycleResult(failed=1)

    monkeypatch.setattr(sweep, "run_cycle", fake_cycle)
    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._web_sweep_once()


def test_cambios_web_quedan_fuera_del_journal():
    """Datos de máquina y revisiones: nada que deshacer ni que copiar a change_logs."""
    from backend.db.models import (
        ClientWebSettings, WebChange, WebChangeItem, WebRunError, WebSnapshot, WebSweepRun, WebWatch, WebWatchState,
    )
    from backend.services import change_journal as cj

    for model in (WebWatch, WebWatchState, WebSweepRun, WebRunError, WebSnapshot, WebChange, WebChangeItem,
                  ClientWebSettings):
        assert model not in cj._SPECS


# ── Red: cortesía y presupuesto ──────────────────────────────────────


def _ok(body=b"<html></html>", code=200, headers=None):
    return FetchResult(status_code=code, elapsed_ms=10, final_url="", headers=headers or {}, body=body)


@pytest.mark.asyncio
async def test_fetch_many_va_en_serie_por_host_y_en_paralelo_entre_hosts():
    active: dict[str, int] = {}
    peak: dict[str, int] = {}

    async def fetcher(url, **kw):
        host = sweep.host_of(url)
        active[host] = active.get(host, 0) + 1
        peak[host] = max(peak.get(host, 0), active[host])
        await asyncio.sleep(0.01)
        active[host] -= 1
        assert kw["max_bytes"] == sweep.MAX_BODY_BYTES and kw["user_agent"] == "UA"
        return _ok()

    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    items = [(i, f"https://h{i % 3}.com/p{i}") for i in range(9)]
    results = await sweep.fetch_many(items, max_concurrency=6, timeout_s=20, delay_ms=300, user_agent="UA",
                                     fetcher=fetcher, sleep=sleep)
    assert set(results) == set(range(9)) and max(peak.values()) == 1
    # Retardo con jitter entre peticiones del MISMO host (2 por host).
    assert len(sleeps) == 6 and all(0.2 <= s <= 0.4 for s in sleeps)


@pytest.mark.asyncio
async def test_fetch_many_respeta_el_presupuesto():
    async def slow(url, **kw):
        if url.endswith("lenta"):
            await asyncio.sleep(5)
        return _ok()

    results = await sweep.fetch_many([(1, "https://a.com/rapida"), (2, "https://b.com/lenta")], max_concurrency=2,
                                     timeout_s=20, delay_ms=0, user_agent=None, fetcher=slow, budget=0.2)
    assert set(results) == {1}


def test_decode_body_usa_el_charset_de_la_cabecera():
    body = "Información".encode("latin-1")
    assert sweep.decode_body(_ok(body, headers={"content-type": "text/html; charset=ISO-8859-1"})) == "Información"
    assert sweep.decode_body(_ok("Ñu".encode())) == "Ñu"
    assert sweep.decode_body(_ok(b"x", headers={"content-type": "text/html; charset=inventado"})) == "x"


def test_un_404_es_respuesta_y_un_timeout_no():
    assert sweep.fetch_ok(_ok(code=404))
    assert not sweep.fetch_ok(FetchResult(None, 15000, "", error="timeout"))
    assert not sweep.fetch_ok(None)


def test_circuit_breaker_por_host():
    watches = [sweep.WatchRow(uuid.uuid4(), 1, f"https://www.fit.es/p{i}", None, False, True, True, False, False,
                              None, None, None) for i in range(5)]
    other = sweep.WatchRow(uuid.uuid4(), 1, "https://otra.es/", None, False, True, True, False, False, None, None, None)
    # Una página bien, una con 403 (bloqueo: también cuenta) y tres sin respuesta.
    codes = [200, 403, None, None, None]
    results = {w.id: FetchResult(code, 1, "", error=None if code else "timeout") for code, w in zip(codes, watches)}
    results[other.id] = FetchResult(None, 1, "", error="timeout")
    assert sweep.circuit_open_hosts(results, [*watches, other]) == {"www.fit.es": (4, 5)}
    assert sweep.unreachable(results[watches[1].id]) and not sweep.unreachable(results[watches[0].id])
    # Un 404 es una respuesta: no es un bloqueo (es un cambio: STATUS_ERROR).
    assert not sweep.unreachable(_ok(code=404))
    assert "caída según el monitor" in sweep.circuit_note("fit.es", 3, 5, "down")
    assert "Probable bloqueo" in sweep.circuit_note("fit.es", 3, 5, None)


# ── compare: lo que corre en el hilo ─────────────────────────────────


PAGE = """<html><head><title>{t}</title></head><body><main><p>Texto fijo de la página.</p>{extra}</main></body></html>"""
FLAGS = {"watch_seo": True, "watch_content": True, "watch_links": False, "watch_html": True}


def _capture(title="A", extra=""):
    return extract(PAGE.format(t=title, extra=extra), base_url="https://x.com/", final_url="https://x.com/",
                   status_code=200)


def test_compare_primera_captura_guarda_cuerpos_y_no_avisa():
    c = _capture()
    result = sweep.compare(capture=c, flags=FLAGS, prev_hashes=None, prev_seo=None, prev_links=None,
                           prev_text_inline=None, prev_text_gz=None, prev_html_gz=None, store_html=True)
    assert result.items == [] and result.text_inline == c.text and result.html_gz is not None


def test_compare_sin_cambios_no_guarda_nada_y_con_html_mide_el_tamano():
    a = _capture()
    same = sweep.compare(capture=a, flags=FLAGS, prev_hashes=a.hashes, prev_seo=a.seo, prev_links=a.links,
                         prev_text_inline=a.text, prev_text_gz=None, prev_html_gz=gzip.compress(a.html.encode()),
                         store_html=True)
    assert same.items == [] and not same.something_changed and same.text_inline is None and same.html_gz is None
    b = _capture(extra='<div class="nueva"><span></span></div>')
    moved = sweep.compare(capture=b, flags=FLAGS, prev_hashes=a.hashes, prev_seo=a.seo, prev_links=a.links,
                          prev_text_inline=a.text, prev_text_gz=None, prev_html_gz=gzip.compress(a.html.encode()),
                          store_html=True)
    (item,) = moved.items
    assert item.rule_code == "HTML_CHANGED" and item.detail["added"] > 0 and item.detail["after_lines"] > 0


# ── Sitemaps ─────────────────────────────────────────────────────────


INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://fit.es/posts.xml</loc></sitemap></sitemapindex>"""
POSTS = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://fit.es/a</loc><lastmod>2026-01-01</lastmod></url><url><loc>https://fit.es/b</loc></url>
<url><loc>ftp://fit.es/c</loc></url><url><loc>https://fit.es/a</loc></url></urlset>"""


@pytest.mark.asyncio
async def test_sitemap_con_indice_anidado_gzip_y_tope():
    from backend.services.web.sitemap import fetch_sitemap_urls

    pages = {"https://fit.es/sitemap.xml": INDEX, "https://fit.es/posts.xml": gzip.compress(POSTS)}

    async def fetcher(url, **kw):
        return _ok(pages[url])

    urls, more = await fetch_sitemap_urls("https://fit.es/sitemap.xml", limit=10, fetcher=fetcher)
    assert urls == ["https://fit.es/a", "https://fit.es/b"] and more is False
    urls, more = await fetch_sitemap_urls("https://fit.es/sitemap.xml", limit=1, fetcher=fetcher)
    assert urls == ["https://fit.es/a"] and more is True


@pytest.mark.asyncio
async def test_sitemap_que_no_responde_dice_por_que():
    from backend.services.web.sitemap import fetch_sitemap_urls

    async def fetcher(url, **kw):
        return FetchResult(None, 1, url, error="unsafe")

    with pytest.raises(ValueError, match="red no pública"):
        await fetch_sitemap_urls("https://fit.es/sitemap.xml", fetcher=fetcher)


def test_sitemap_no_resuelve_entidades_ni_se_infla():
    from backend.services.web import sitemap

    xxe = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
    <urlset><url><loc>https://fit.es/&e;</loc></url></urlset>"""
    urls, _ = sitemap._parse(xxe)
    assert all("root:" not in u for u in urls)
    bomba = gzip.compress(b"<urlset>" + b" " * (60 * 1024 * 1024) + b"</urlset>")
    with pytest.raises(ValueError, match="demasiado grande"):
        sitemap._parse(bomba)


# ── Validación al guardar ────────────────────────────────────────────


def test_selectores_y_expresiones_se_validan_al_guardar():
    from pydantic import ValidationError

    from backend.schemas.web import WatchCreate, WatchUpdate

    created = WatchCreate(url="Fit.es/curso?x=1#seccion", content_selector="  ")
    assert created.url == "https://fit.es/curso?x=1" and created.content_selector is None
    for bad in ({"ignore_selectors": ["<<<"]}, {"ignore_regexes": ["[sin-cerrar"]}):
        with pytest.raises(ValidationError):
            WatchUpdate(**bad)
    for url in ("http://10.0.0.1/", "https://fit.es:8080/", "http://db.railway.internal/"):
        with pytest.raises(ValidationError):
            WatchCreate(url=url)
    assert WatchUpdate(ignore_selectors=None).model_fields_set == {"ignore_selectors"}
