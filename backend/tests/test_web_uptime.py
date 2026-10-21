"""Monitor de caídas (Webs fase 1): clasificación, máquina de estados, falsas
alarmas, SSRF, Slack y job. Sin red: todo va con transports y DNS falsos."""
from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.services.web import safe_http, slack, uptime
from backend.services.web.safe_http import FetchResult, SSRFError, UnresolvableHost
from backend.services.web.uptime import Probe, Snapshot, UptimeConfig, advance, classify

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
CFG = UptimeConfig(interval=300, recheck=60, failures_to_alert=2, recoveries_to_close=2, blocked_minutes=60)


def _res(code=None, *, error=None, headers=None, body=b"") -> FetchResult:
    return FetchResult(status_code=code, elapsed_ms=120, final_url="https://ejemplo.com/",
                       headers=headers or {}, body=body, error=error)


# ── Clasificación ────────────────────────────────────────────────────


@pytest.mark.parametrize("code", [200, 204, 301, 302, 304])
def test_2xx_y_3xx_es_arriba(code):
    assert classify(_res(code)) == Probe("up", None, code, 120)


@pytest.mark.parametrize("code", [500, 502, 503, 504, 404, 410, 400, 418, 451])
def test_5xx_404_410_y_otros_4xx_son_caida(code):
    probe = classify(_res(code))
    assert (probe.outcome, probe.cause, probe.status_code) == ("down", f"http_{code}", code)


@pytest.mark.parametrize("code", [401, 403, 429])
def test_401_403_429_son_bloqueo_no_caida(code):
    probe = classify(_res(code))
    assert (probe.outcome, probe.cause) == ("blocked", f"http_{code}")


def test_desafio_de_cloudflare_es_bloqueo_aunque_sea_503():
    assert classify(_res(503, headers={"cf-mitigated": "challenge"})).outcome == "blocked"
    page = classify(_res(403, headers={"server": "cloudflare"}, body=b"<title>Just a moment...</title>"))
    assert (page.outcome, page.cause) == ("blocked", "challenge")
    # Un 503 de un servidor cualquiera sigue siendo una caída.
    assert classify(_res(503, headers={"server": "nginx"}, body=b"Just a moment")).outcome == "down"


@pytest.mark.parametrize("error", ["timeout", "dns", "connect", "tls", "unsafe", "redirects", "error"])
def test_errores_de_red_son_caida(error):
    probe = classify(_res(None, error=error))
    assert (probe.outcome, probe.cause, probe.status_code) == ("down", error, None)


def test_etiquetas_y_duraciones():
    assert uptime.cause_label("http_503") == "error HTTP 503"
    assert uptime.cause_label("dns") == "el dominio no resuelve (DNS)"
    assert uptime.format_duration(timedelta(minutes=23)) == "23 min"
    assert uptime.format_duration(timedelta(hours=2, minutes=5)) == "2 h 5 min"
    assert uptime.format_duration(timedelta(days=1, hours=3)) == "1 d 3 h"
    assert uptime.local_when(datetime(2026, 10, 21, 8, 2, tzinfo=UTC)) == "21/10 a las 10:02"


# ── Máquina de estados ───────────────────────────────────────────────


def _run(outcomes, *, start=Snapshot(), open_kind=None, step=timedelta(minutes=1)):
    """Aplica resultados seguidos y devuelve las transiciones (con la caída abierta simulada)."""
    state, now, out = start, NOW, []
    for outcome in outcomes:
        t = advance(state, outcome, now, open_kind, CFG)
        if t.close:
            open_kind = None
        if t.open_kind:
            open_kind = t.open_kind
        out.append((t, open_kind))
        state, now = t.state, now + step
    return out


def test_sano_se_mira_cada_cinco_minutos():
    (t, kind), = _run(["up"])
    assert t.state.status == "up" and kind is None
    assert t.next_check_at == NOW + timedelta(seconds=300)
    assert t.state.status_since == NOW


def test_primer_fallo_es_sospecha_y_se_recomprueba_al_minuto():
    (t, kind), = _run(["down"], start=Snapshot(status="up"))
    assert t.state.status == "suspect" and kind is None and t.open_kind is None
    assert t.next_check_at == NOW + timedelta(seconds=60)


def test_dos_ciclos_fallidos_abren_la_caida_desde_el_primer_fallo():
    (first, _), (second, kind) = _run(["down", "down"], start=Snapshot(status="up"))
    assert second.open_kind == "down" and kind == "down"
    assert second.open_started_at == NOW  # el primer fallo, no la confirmación
    assert second.state.status == "down"
    assert second.next_check_at == NOW + timedelta(minutes=1, seconds=60)


def test_sospecha_que_se_recupera_no_avisa():
    steps = _run(["down", "up"], start=Snapshot(status="up"))
    assert all(t.open_kind is None and not t.close for t, _ in steps)
    assert steps[-1][0].state.status == "up" and steps[-1][0].state.failures == 0


def test_hacen_falta_dos_ciclos_buenos_para_cerrar():
    steps = _run(["down", "down", "up", "up"], start=Snapshot(status="up"))
    third, fourth = steps[2][0], steps[3][0]
    assert third.state.status == "down" and not third.close and third.state.successes == 1
    assert fourth.close and fourth.state.status == "up" and fourth.state.successes == 0
    # Un fallo entre medias reinicia la cuenta.
    steps = _run(["down", "down", "up", "down", "up"], start=Snapshot(status="up"))
    assert not any(t.close for t, _ in steps)


def test_bloqueo_corto_no_avisa_y_largo_abre_aviso_de_bloqueo():
    steps = _run(["blocked"] * 3, start=Snapshot(status="up"), step=timedelta(minutes=30))
    assert [t.open_kind for t, _ in steps] == [None, None, "blocked"]
    assert steps[2][0].open_started_at == NOW
    assert all(t.state.status == "blocked" for t, _ in steps)
    assert steps[0][0].next_check_at == NOW + timedelta(seconds=300)


def test_bloqueo_abierto_se_cierra_con_una_respuesta_buena():
    blocked = Snapshot(status="blocked", blocked_since=NOW - timedelta(hours=2))
    (t, kind), = _run(["up"], start=blocked, open_kind="blocked")
    assert t.close and kind is None and t.state.status == "up" and t.state.blocked_since is None


def test_de_bloqueo_a_caida_cierra_el_bloqueo_y_abre_la_caida():
    blocked = Snapshot(status="blocked", blocked_since=NOW - timedelta(hours=2))
    steps = _run(["down", "down"], start=blocked, open_kind="blocked")
    assert steps[0][0].state.status == "suspect" and not steps[0][0].close
    assert steps[1][0].close and steps[1][0].open_kind == "down" and steps[1][1] == "down"


def test_caida_que_pasa_a_responder_con_403_se_da_por_recuperada():
    down = Snapshot(status="down", failures=4, failing_since=NOW - timedelta(minutes=10))
    steps = _run(["blocked", "blocked"], start=down, open_kind="down")
    assert steps[0][0].state.status == "down" and not steps[0][0].close
    assert steps[1][0].close and steps[1][0].state.status == "blocked"
    assert steps[1][0].state.blocked_since is not None


# ── Reintento, canario y correlación ─────────────────────────────────


async def test_un_fallo_se_reintenta_en_el_mismo_ciclo():
    answers = [_res(None, error="timeout"), _res(200)]
    sleeps = []

    async def fetcher(url, **_kw):
        return answers.pop(0)

    async def sleep(seconds):
        sleeps.append(seconds)

    probe = await uptime.probe("https://ejemplo.com/", fetcher=fetcher, sleep=sleep)
    assert probe.outcome == "up" and len(sleeps) == 1 and 5 <= sleeps[0] <= 10


@pytest.mark.parametrize("first", [_res(200), _res(403)])
async def test_lo_que_no_es_caida_no_se_reintenta(first):
    calls = []

    async def fetcher(url, **_kw):
        calls.append(url)
        return first

    await uptime.probe("https://ejemplo.com/", fetcher=fetcher, sleep=lambda s: asyncio.sleep(0))
    assert len(calls) == 1


async def test_canario():
    async def dead(url, **_kw):
        return _res(None, error="timeout")

    async def one_alive(url, **_kw):
        return _res(204) if "google" in url else _res(None, error="dns")

    urls = ["https://www.google.com/generate_204", "https://cloudflare.com/"]
    assert await uptime.connectivity_ok(urls, fetcher=dead) is False
    assert await uptime.connectivity_ok(urls, fetcher=one_alive) is True
    assert await uptime.connectivity_ok([], fetcher=dead) is True


def _targets(n):
    return [uptime.DueTarget(i, f"https://h{i}.com/", None, f"h{i}.com") for i in range(1, n + 1)]


def test_correlacion_de_fallos_de_red():
    down = Probe("down", "timeout", None, 15000)
    ok = Probe("up", None, 200, 100)
    targets = _targets(4)
    assert uptime.network_problem(targets, {1: down, 2: down, 3: down, 4: ok}) is True
    # Dos hosts no bastan, aunque sean la mitad.
    assert uptime.network_problem(_targets(4), {1: down, 2: down, 3: ok, 4: ok}) is False
    # Tres de ocho no llegan a la mitad.
    eight = _targets(8)
    assert uptime.network_problem(eight, {t.id: (down if t.id <= 3 else ok) for t in eight}) is False
    # Un 5xx es una respuesta del servidor: nuestra red funciona.
    http = Probe("down", "http_503", 503, 100)
    assert uptime.network_problem(targets, {1: http, 2: http, 3: http, 4: ok}) is False


async def test_cada_host_en_serie_y_como_mucho_ocho_a_la_vez():
    targets = [uptime.DueTarget(i, f"https://h{i % 12}.com/p{i}", None, f"h{i % 12}.com") for i in range(36)]
    running: dict[str, int] = {}
    peak = {"global": 0, "host": 0}

    async def fetcher(url, **_kw):
        host = httpx.URL(url).host
        running[host] = running.get(host, 0) + 1
        peak["host"] = max(peak["host"], running[host])
        peak["global"] = max(peak["global"], sum(running.values()))
        await asyncio.sleep(0.01)
        running[host] -= 1
        return _res(200)

    results = await uptime.probe_all(targets, fetcher=fetcher)
    assert len(results) == 36 and peak["host"] == 1 and peak["global"] <= uptime.MAX_CONCURRENCY


async def test_lo_que_no_cabe_en_el_presupuesto_queda_para_el_siguiente_ciclo():
    async def fetcher(url, **_kw):
        if "lento" in url:
            await asyncio.sleep(5)
        return _res(200)

    targets = [uptime.DueTarget(1, "https://rapido.com/", None, "rapido.com"),
               uptime.DueTarget(2, "https://lento.com/", None, "lento.com")]
    results = await uptime.probe_all(targets, fetcher=fetcher, budget=0.2)
    assert set(results) == {1}


# ── SSRF ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "ftp://ejemplo.com/", "file:///etc/passwd", "https://ejemplo.com:8080/", "http://ejemplo.com:22/",
    "https://user:pass@ejemplo.com/", "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd12::1]/",
    "http://web.railway.internal/", "http://postgres.railway.internal:443/", "http://metadata.google.internal/",
    "http://intranet/", "http://impresora.local/", "http://100.64.0.1/", "",
])
def test_urls_rechazadas_sin_tocar_la_red(url):
    with pytest.raises(SSRFError):
        safe_http.check_url_syntax(url)


@pytest.mark.parametrize("url", ["https://ejemplo.com/", "http://ejemplo.com:80/x?y=1", "https://ejemplo.com:443/", "https://8.8.8.8/"])
def test_urls_publicas_aceptadas(url):
    assert safe_http.check_url_syntax(url)


def _dns(monkeypatch, mapping):
    def fake_getaddrinfo(host, *_a, **_kw):
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
                for ip in mapping[host]]
    monkeypatch.setattr(safe_http.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("ips", [
    ["10.0.0.7"], ["169.254.169.254"], ["127.0.0.1"], ["fd12:3456::1"], ["::ffff:10.0.0.1"],
    ["93.184.216.34", "192.168.0.10"],  # basta una interna
])
def test_dns_que_resuelve_a_ip_interna_se_rechaza(monkeypatch, ips):
    _dns(monkeypatch, {"trampa.com": ips})
    with pytest.raises(SSRFError):
        safe_http.resolve_public_ip("trampa.com")


def test_nxdomain_es_host_no_resoluble(monkeypatch):
    _dns(monkeypatch, {})
    with pytest.raises(UnresolvableHost):
        safe_http.resolve_public_ip("no-existe.com")


def _mock(monkeypatch, handler, dns=None):
    _dns(monkeypatch, dns if dns is not None else {"ejemplo.com": ["93.184.216.34"], "otro.com": ["93.184.216.35"]})
    return lambda pins: safe_http.PinnedTransport(httpx.MockTransport(handler), pins)


async def test_conecta_a_la_ip_fijada_conservando_host_y_sni(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(host=request.url.host, header=request.headers["host"],
                    sni=request.extensions.get("sni_hostname"), ua=request.headers["user-agent"])
        return httpx.Response(200, text="ok")

    result = await safe_http.fetch("https://ejemplo.com/", user_agent="UA-cliente",
                                   transport_factory=_mock(monkeypatch, handler))
    assert result.status_code == 200 and result.error is None
    assert seen == {"host": "93.184.216.34", "header": "ejemplo.com", "sni": "ejemplo.com", "ua": "UA-cliente"}


@pytest.mark.parametrize("location", [
    "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/", "https://ejemplo.com:8443/",
    "http://web.railway.internal/",
])
async def test_redireccion_a_destino_prohibido_se_corta(monkeypatch, location):
    hits = []

    def handler(request):
        hits.append(str(request.url))
        return httpx.Response(302, headers={"location": location})

    result = await safe_http.fetch("https://ejemplo.com/", transport_factory=_mock(monkeypatch, handler))
    assert result.error == "unsafe" and len(hits) == 1


async def test_redireccion_a_host_que_resuelve_interno_se_corta(monkeypatch):
    def handler(request):
        return httpx.Response(301, headers={"location": "https://otro.com/"})

    factory = _mock(monkeypatch, handler, dns={"ejemplo.com": ["93.184.216.34"], "otro.com": ["fd12::5"]})
    assert (await safe_http.fetch("https://ejemplo.com/", transport_factory=factory)).error == "unsafe"


async def test_redirecciones_revalidadas_y_limitadas(monkeypatch):
    def handler(request):
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"location": f"https://otro.com/{n + 1}"}) if n < 3 else httpx.Response(200)

    result = await safe_http.fetch("https://ejemplo.com/0", transport_factory=_mock(monkeypatch, handler))
    assert result.status_code == 200 and result.redirects == 3 and result.final_url == "https://otro.com/3"

    def loop(request):
        return httpx.Response(302, headers={"location": "https://ejemplo.com/"})

    looped = await safe_http.fetch("https://ejemplo.com/", transport_factory=_mock(monkeypatch, loop))
    assert looped.error == "redirects" and looped.redirects == safe_http.MAX_REDIRECTS


async def test_cuerpo_acotado(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"x" * (200 * 1024))

    result = await safe_http.fetch("https://ejemplo.com/", transport_factory=_mock(monkeypatch, handler))
    assert len(result.body) == safe_http.MAX_BODY_BYTES


@pytest.mark.parametrize("exc,kind", [
    (httpx.ReadTimeout("lento"), "timeout"),
    (httpx.ConnectTimeout("lento"), "timeout"),
    (httpx.ConnectError("Connection refused"), "connect"),
    (httpx.ReadError("Connection reset by peer"), "connect"),
])
async def test_errores_de_red_tipificados(monkeypatch, exc, kind):
    def handler(request):
        raise exc

    assert (await safe_http.fetch("https://ejemplo.com/", transport_factory=_mock(monkeypatch, handler))).error == kind


async def test_error_de_certificado_es_tls(monkeypatch):
    def handler(request):
        try:
            raise ssl.SSLCertVerificationError(1, "certificate verify failed")
        except ssl.SSLError as cause:
            raise httpx.ConnectError("handshake") from cause

    assert (await safe_http.fetch("https://ejemplo.com/", transport_factory=_mock(monkeypatch, handler))).error == "tls"


async def test_dns_caido_y_tiempo_total(monkeypatch):
    factory = _mock(monkeypatch, lambda r: httpx.Response(200), dns={})
    assert (await safe_http.fetch("https://ejemplo.com/", transport_factory=factory)).error == "dns"

    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200)

    _dns(monkeypatch, {"ejemplo.com": ["93.184.216.34"]})
    factory = lambda pins: safe_http.PinnedTransport(httpx.MockTransport(slow), pins)  # noqa: E731
    assert (await safe_http.fetch("https://ejemplo.com/", timeout=0.2, transport_factory=factory)).error == "timeout"


async def test_host_no_fijado_falla_cerrado():
    transport = safe_http.PinnedTransport(httpx.MockTransport(lambda r: httpx.Response(200)), {})
    with pytest.raises(SSRFError):
        await transport.handle_async_request(httpx.Request("GET", "https://ejemplo.com/"))


# ── Validación al guardar ────────────────────────────────────────────


def test_validacion_al_guardar():
    from pydantic import ValidationError

    from backend.schemas.web import SlackSettingsUpdate, UptimeTargetCreate

    assert UptimeTargetCreate(url="Ejemplo.com").url == "https://ejemplo.com/"
    assert UptimeTargetCreate(url="http://ejemplo.com:80/tienda?x=1#ancla").url == "http://ejemplo.com/tienda?x=1"
    for bad in ("http://10.0.0.1/", "https://ejemplo.com:8080/", "http://api.railway.internal/", "javascript:alert(1)"):
        with pytest.raises(ValidationError):
            UptimeTargetCreate(url=bad)
    with pytest.raises(ValidationError):
        SlackSettingsUpdate(webhook_url="https://evil.com/services/T/B/X")
    ok = SlackSettingsUpdate(webhook_url=" https://hooks.slack.com/services/T0/B1/abc123 ", channel_hint=" ")
    assert ok.webhook_url.get_secret_value() == "https://hooks.slack.com/services/T0/B1/abc123"
    assert ok.channel_hint is None


# ── Slack ────────────────────────────────────────────────────────────

HOOK = "https://hooks.slack.com/services/T0/B1/abc123"


@pytest.mark.parametrize("code,ok,revoked", [(200, True, False), (404, False, True), (410, False, True),
                                             (500, False, False), (400, False, False)])
async def test_slack_resultados(code, ok, revoked):
    sent = {}

    def handler(request):
        sent["body"] = request.content
        return httpx.Response(code, text="ok" if code == 200 else "no_service")

    result = await slack.post_message(HOOK, "La web no responde", transport=httpx.MockTransport(handler))
    assert (result.ok, result.revoked) == (ok, revoked)
    assert b"La web no responde" in sent["body"]


async def test_slack_red_caida_no_lanza_y_webhook_ajeno_ni_se_intenta():
    def boom(request):
        raise httpx.ConnectError("sin red")

    result = await slack.post_message(HOOK, "x", transport=httpx.MockTransport(boom))
    assert not result.ok and not result.revoked
    calls = []
    result = await slack.post_message("https://evil.com/x", "x", transport=httpx.MockTransport(lambda r: calls.append(r)))
    assert not result.ok and calls == []
    assert slack.normalize_channel("seo") == "#seo" and slack.normalize_channel("  ") is None


# ── Job, catálogo y Deshacer ─────────────────────────────────────────


def test_job_uptime_en_el_catalogo(monkeypatch):
    from backend.config import settings
    from backend.services.job_catalog import job_definitions

    monkeypatch.setattr(settings, "UPTIME_ENABLED", False)
    definitions = {d.spec.key: d for d in job_definitions()}
    spec = definitions["uptime"].spec
    assert (spec.lock_id, spec.interval_seconds, spec.timeout_seconds, spec.retry_seconds) == (15, 60, 150, 60)
    assert not definitions["uptime"].enabled
    locks = [d.spec.lock_id for d in definitions.values()]
    assert len(locks) == len(set(locks))
    # 16 (web_sweep) y 17 (gsc_detail) están reservados.
    assert not {16, 17} & {d.spec.lock_id for k, d in definitions.items() if k not in ("web_sweep", "gsc_detail")}
    monkeypatch.setattr(settings, "UPTIME_ENABLED", True)
    assert {d.spec.key: d for d in job_definitions()}["uptime"].enabled


@pytest.mark.parametrize("flags,code", [({"canary_failed": True}, "provider_unavailable"),
                                        ({"network_issue": True}, "provider_unavailable"),
                                        ({"failed": 1}, "partial_failure")])
async def test_el_job_informa_de_fallos(monkeypatch, flags, code):
    from backend.services.job_runtime import JobFailure
    from backend.startup import background_tasks

    async def fake_cycle(_factory):
        return uptime.CycleResult(**flags)

    monkeypatch.setattr(uptime, "run_cycle", fake_cycle)
    with pytest.raises(JobFailure, match=code):
        await background_tasks._uptime_once()


async def test_el_job_sin_problemas_no_falla(monkeypatch):
    from backend.startup import background_tasks

    async def fake_cycle(_factory):
        return uptime.CycleResult(due=3, probed=3, applied=3)

    monkeypatch.setattr(uptime, "run_cycle", fake_cycle)
    await background_tasks._uptime_once()


def test_webs_quedan_fuera_del_journal():
    """Datos de máquina y un webhook cifrado: nada que deshacer y nada que copiar a change_logs."""
    from backend.db.models import ClientWebSettings, WebOutage, WebUptimeProbe, WebUptimeState, WebUptimeTarget
    from backend.services import change_journal as cj

    for model in (WebUptimeTarget, WebUptimeState, WebOutage, WebUptimeProbe, ClientWebSettings):
        assert model not in cj._SPECS
