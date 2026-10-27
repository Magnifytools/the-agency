"""Salud diaria de las webs (caducidad de certificado y dominio, robots.txt y
sitemap) y revisión tras publicar. Sin red: DNS, TLS y HTTP falsos."""
from __future__ import annotations

import json
import socket
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.db.models import WebRobotsState
from backend.services.web import health, publish_check, safe_http
from backend.services.web.health import (
    RobotsRead, SitemapRead, apply_robots, blocks_all, days_left, domain_candidates, level, lookup_domain,
    parse_bootstrap, parse_robots, rdap_expiration, read_robots, read_sitemap, robots_hash,
)
from backend.services.web.safe_http import FetchResult

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)


def _res(code=None, *, body=b"", error=None, url="https://ejemplo.com/", headers=None, redirects=0):
    return FetchResult(status_code=code, elapsed_ms=50, final_url=url, redirects=redirects,
                       headers=headers or {}, body=body, error=error)


def _dns(monkeypatch, mapping):
    def fake_getaddrinfo(host, *_a, **_kw):
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in mapping[host]]
    monkeypatch.setattr(safe_http.socket, "getaddrinfo", fake_getaddrinfo)


def _cert_der(not_after: datetime, issuer: str = "Let's Encrypt") -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ejemplo.com")])
    issuer_name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, issuer)])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(not_after - timedelta(days=90)).not_valid_after(not_after)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


# ── Umbrales ─────────────────────────────────────────────────────────


def test_dias_y_niveles():
    assert days_left(NOW + timedelta(days=14, hours=23), NOW) == 14
    assert days_left(NOW + timedelta(hours=3), NOW) == 0
    assert days_left(NOW - timedelta(hours=3), NOW) == -1
    assert days_left(None, NOW) is None
    assert level(15, 14, 3) == "ok" and level(14, 14, 3) == "warning"
    assert level(3, 14, 3) == "critical" and level(-5, 14, 3) == "critical"
    assert level(None, 14, 3) is None


# ── Certificado TLS (mismas garantías que safe_http.fetch) ───────────


async def test_certificado_valido_conecta_a_la_ip_fijada_con_sni(monkeypatch):
    _dns(monkeypatch, {"ejemplo.com": ["93.184.216.34"]})
    seen = []
    expires = datetime(2026, 11, 5, tzinfo=UTC)

    async def opener(ip, port, context, server_hostname, timeout):
        seen.append((ip, port, server_hostname, context.verify_mode))
        return _cert_der(expires)

    cert = await safe_http.fetch_tls_certificate("ejemplo.com", opener=opener)
    assert cert.error is None and cert.verified and cert.not_after == expires
    assert cert.issuer == "Let's Encrypt"
    assert seen == [("93.184.216.34", 443, "ejemplo.com", ssl.CERT_REQUIRED)]


async def test_certificado_no_valido_se_relee_sin_verificar_para_saber_la_fecha(monkeypatch):
    _dns(monkeypatch, {"ejemplo.com": ["93.184.216.34"]})
    expired = datetime(2026, 10, 1, tzinfo=UTC)
    modes = []

    async def opener(ip, port, context, server_hostname, timeout):
        modes.append(context.verify_mode)
        if context.verify_mode == ssl.CERT_REQUIRED:
            exc = ssl.SSLCertVerificationError("certificate verify failed")
            exc.verify_message = "certificate has expired"
            raise exc
        return _cert_der(expired)

    cert = await safe_http.fetch_tls_certificate("ejemplo.com", opener=opener)
    assert modes == [ssl.CERT_REQUIRED, ssl.CERT_NONE]
    assert not cert.verified and cert.verify_error == "certificate has expired" and cert.not_after == expired


@pytest.mark.parametrize("ips", [["10.0.0.7"], ["169.254.169.254"], ["93.184.216.34", "192.168.1.1"]])
async def test_certificado_de_host_que_resuelve_interno_ni_se_intenta(monkeypatch, ips):
    _dns(monkeypatch, {"trampa.com": ips})
    calls = []

    async def opener(*args):
        calls.append(args)
        return b""

    cert = await safe_http.fetch_tls_certificate("trampa.com", opener=opener)
    assert cert.error == "unsafe" and calls == []


async def test_certificado_puerto_no_permitido_dns_y_errores_de_conexion(monkeypatch):
    _dns(monkeypatch, {"ejemplo.com": ["93.184.216.34"]})

    async def never(*_args):
        raise AssertionError("no debería conectar")

    assert (await safe_http.fetch_tls_certificate("ejemplo.com", port=8443, opener=never)).error == "unsafe"
    assert (await safe_http.fetch_tls_certificate("no-existe.com", opener=never)).error == "dns"
    assert (await safe_http.fetch_tls_certificate("localhost", opener=never)).error == "unsafe"

    async def refused(*_args):
        raise ConnectionRefusedError()

    async def handshake(*_args):
        raise ssl.SSLError("wrong version number")

    async def slow(*_args):
        raise TimeoutError()

    assert (await safe_http.fetch_tls_certificate("ejemplo.com", opener=refused)).error == "connect"
    assert (await safe_http.fetch_tls_certificate("ejemplo.com", opener=handshake)).error == "tls"
    assert (await safe_http.fetch_tls_certificate("ejemplo.com", opener=slow)).error == "timeout"


async def test_fetch_acepta_otra_cabecera_accept(monkeypatch):
    _dns(monkeypatch, {"rdap.ejemplo.net": ["93.184.216.40"]})
    seen = {}

    def handler(request):
        seen["accept"] = request.headers["accept"]
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json={})

    factory = lambda pins: safe_http.PinnedTransport(httpx.MockTransport(handler), pins)  # noqa: E731
    result = await safe_http.fetch("https://rdap.ejemplo.net/domain/x.com", accept="application/rdap+json",
                                   transport_factory=factory)
    assert result.status_code == 200 and seen["accept"] == "application/rdap+json"
    assert "Mozilla" in seen["ua"]


# ── Dominio (RDAP) ───────────────────────────────────────────────────

BOOTSTRAP = parse_bootstrap({"services": [
    [["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
    [["uk"], ["http://rdap.nominet.uk/uk/", "https://rdap.nominet.uk/uk/"]],
    [["io"], ["https://rdap.nic.io"]],
]})


def test_registro_de_la_iana_y_candidatos():
    assert BOOTSTRAP["com"] == "https://rdap.verisign.com/com/v1/"
    assert BOOTSTRAP["uk"] == "https://rdap.nominet.uk/uk/"  # la https, no la http
    assert BOOTSTRAP["io"] == "https://rdap.nic.io/"
    assert domain_candidates("www.ejemplo.com") == ["ejemplo.com"]
    assert domain_candidates("blog.ejemplo.co.uk") == ["blog.ejemplo.co.uk", "ejemplo.co.uk", "co.uk"]
    assert domain_candidates("a.b.c.d.e.ejemplo.com") == ["c.d.e.ejemplo.com", "d.e.ejemplo.com", "e.ejemplo.com",
                                                          "ejemplo.com"]


def test_fecha_de_caducidad_rdap():
    data = {"events": [{"eventAction": "registration", "eventDate": "2010-01-01T00:00:00Z"},
                       {"eventAction": "expiration", "eventDate": "2027-01-15T10:00:00Z"}]}
    assert rdap_expiration(data) == datetime(2027, 1, 15, 10, tzinfo=UTC)
    assert rdap_expiration({"events": []}) is None
    assert rdap_expiration({"events": [{"eventAction": "expiration", "eventDate": "basura"}]}) is None


async def test_dominio_registrable_del_mas_largo_al_mas_corto():
    calls = []

    async def fetcher(url, **kwargs):
        calls.append((url, kwargs.get("accept")))
        if url.endswith("/domain/ejemplo.co.uk"):
            body = {"events": [{"eventAction": "expiration", "eventDate": "2026-11-10T00:00:00Z"}]}
            return _res(200, body=json.dumps(body).encode(), url=url)
        return _res(404, url=url)

    info = await lookup_domain("blog.ejemplo.co.uk", BOOTSTRAP, fetcher=fetcher)
    assert (info.status, info.name, info.expires_at) == ("ok", "ejemplo.co.uk", datetime(2026, 11, 10, tzinfo=UTC))
    assert [c[0] for c in calls] == ["https://rdap.nominet.uk/uk/domain/blog.ejemplo.co.uk",
                                     "https://rdap.nominet.uk/uk/domain/ejemplo.co.uk"]
    assert all("application/rdap+json" in c[1] for c in calls)


async def test_tld_sin_rdap_es_unsupported_sin_preguntar():
    async def fetcher(url, **_kwargs):
        raise AssertionError("no debería preguntar")

    info = await lookup_domain("www.cliente.es", BOOTSTRAP, fetcher=fetcher)
    assert info.status == "unsupported" and info.expires_at is None


async def test_dominio_sin_fecha_no_encontrado_y_errores():
    async def no_date(url, **_kwargs):
        return _res(200, body=b'{"events": []}', url=url)

    async def not_found(url, **_kwargs):
        return _res(404, url=url)

    async def down(url, **_kwargs):
        return _res(error="timeout", url=url)

    async def rate_limited(url, **_kwargs):
        return _res(429, url=url)

    assert (await lookup_domain("ejemplo.com", BOOTSTRAP, fetcher=no_date)).status == "no_date"
    assert (await lookup_domain("ejemplo.com", BOOTSTRAP, fetcher=not_found)).status == "not_found"
    timeout = await lookup_domain("ejemplo.com", BOOTSTRAP, fetcher=down)
    assert timeout.status == "error" and timeout.error == "no responde a tiempo"
    assert "429" in (await lookup_domain("ejemplo.com", BOOTSTRAP, fetcher=rate_limited)).error
    assert (await lookup_domain("ejemplo.com", None, fetcher=down)).status == "error"
    assert (await lookup_domain("93.184.216.34", BOOTSTRAP, fetcher=down)).status == "not_found"


# ── robots.txt ───────────────────────────────────────────────────────


@pytest.mark.parametrize("body,blocked", [
    ("User-agent: *\nDisallow: /", True),
    ("User-agent: *\r\nDisallow: /   # todo fuera\r\n", True),
    ("User-agent: Googlebot\nDisallow: /", True),
    ("User-agent: Bingbot\nUser-agent: *\nDisallow: /*", True),
    ("User-agent: *\nDisallow: /\nAllow: /", False),
    ("User-agent: *\nDisallow:", False),
    ("User-agent: *\nDisallow: /admin/", False),
    ("User-agent: GPTBot\nDisallow: /", False),
    ("# Disallow: /\nUser-agent: *\nAllow: /", False),
    ("", False),
])
def test_bloqueo_total(body, blocked):
    assert blocks_all(body) is blocked


def test_grupos_y_sitemaps_declarados():
    groups, sitemaps = parse_robots(
        "Sitemap: https://ejemplo.com/sitemap_index.xml\nUser-agent: a\nUser-agent: b\nDisallow: /x\n"
        "User-agent: c\nAllow: /y\nsitemap: https://cdn.ejemplo.com/s.xml\n")
    assert groups == {"a": [("disallow", "/x")], "b": [("disallow", "/x")], "c": [("allow", "/y")]}
    assert sitemaps == ["https://ejemplo.com/sitemap_index.xml", "https://cdn.ejemplo.com/s.xml"]


def test_hash_ignora_saltos_de_linea_y_espacios_finales():
    assert robots_hash("User-agent: *\r\nDisallow: /x  \r\n") == robots_hash("User-agent: *\nDisallow: /x\n")
    assert robots_hash("User-agent: *\nDisallow: /x") != robots_hash("User-agent: *\nDisallow: /y")


def test_lectura_de_robots():
    ok = read_robots(_res(200, body=b"\xef\xbb\xbfUser-agent: *\nSitemap: https://ejemplo.com/s.xml",
                          headers={"content-type": "text/plain; charset=utf-8"}))
    assert ok.status == "ok" and ok.body.startswith("User-agent") and ok.sitemaps == ("https://ejemplo.com/s.xml",)
    assert read_robots(_res(404)) == RobotsRead("missing", body="")
    assert read_robots(_res(503)) == RobotsRead("error", error="error HTTP 503")
    assert read_robots(_res(error="dns")).error == "el dominio no resuelve (DNS)"


SITEMAP_OK = SitemapRead("https://ejemplo.com/sitemap.xml", "default", "ok", count=3, has_more=False)


def test_cambio_de_robots_guarda_el_anterior_y_pide_revision():
    row = WebRobotsState(client_id=1, origin="https://ejemplo.com", robots_blocks_all=False)
    assert apply_robots(row, RobotsRead("ok", body="User-agent: *\nDisallow: /admin/"), SITEMAP_OK, NOW) is False
    assert row.robots_changed_at is None and row.robots_hash is not None and not row.robots_blocks_all

    later = NOW + timedelta(days=1)
    row.robots_reviewed_at = NOW  # una revisión anterior no tapa el cambio nuevo
    assert apply_robots(row, RobotsRead("ok", body="User-agent: *\nDisallow: /"), SITEMAP_OK, later) is True
    assert row.robots_changed_at == later and row.robots_reviewed_at is None
    assert row.robots_previous_body == "User-agent: *\nDisallow: /admin/" and row.robots_blocks_all

    # Un día sin poder leerlo no cuenta como cambio ni borra lo último leído.
    assert apply_robots(row, RobotsRead("error", error="error HTTP 503"), SITEMAP_OK, later) is False
    assert row.robots_status == "error" and row.robots_body == "User-agent: *\nDisallow: /" and row.robots_blocks_all

    # Desaparecer (404) es un cambio: para Google ya no hay reglas.
    assert apply_robots(row, RobotsRead("missing", body=""), SITEMAP_OK, later) is True
    assert row.robots_status == "missing" and not row.robots_blocks_all


def test_cuerpo_guardado_acotado():
    row = WebRobotsState(client_id=1, origin="https://ejemplo.com", robots_blocks_all=False)
    apply_robots(row, RobotsRead("ok", body="#" * (health.ROBOTS_STORED_CHARS + 500)), SITEMAP_OK, NOW)
    assert len(row.robots_body) == health.ROBOTS_STORED_CHARS


# ── Sitemap ──────────────────────────────────────────────────────────

URLSET = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          b"<url><loc>https://ejemplo.com/a</loc></url><url><loc>https://ejemplo.com/b</loc></url></urlset>")


async def test_sitemap_declarado_o_por_defecto(monkeypatch):
    asked = []

    async def fetcher(url, **_kwargs):
        asked.append(url)
        return _res(200, body=URLSET, url=url)

    declared = await read_sitemap("https://ejemplo.com", RobotsRead("ok", body="", sitemaps=("https://ejemplo.com/s.xml",)),
                                  None, fetcher=fetcher)
    assert (declared.source, declared.status, declared.count, declared.url) == ("declared", "ok", 2, "https://ejemplo.com/s.xml")
    default = await read_sitemap("https://ejemplo.com", RobotsRead("missing", body=""), None, fetcher=fetcher)
    assert (default.source, default.url) == ("default", "https://ejemplo.com/sitemap.xml")
    assert asked == ["https://ejemplo.com/s.xml", "https://ejemplo.com/sitemap.xml"]


@pytest.mark.parametrize("result,status", [
    (_res(404), "error"),
    (_res(error="timeout"), "error"),
    (_res(200, body=b"<!doctype html><html><body>Not found</body></html>"), "empty"),
    (_res(200, body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'), "empty"),
    (_res(200, body=b"\x1f\x8bbasura"), "invalid"),
])
async def test_sitemap_que_no_sirve(result, status):
    async def fetcher(url, **_kwargs):
        return result

    read = await read_sitemap("https://ejemplo.com", RobotsRead("missing", body=""), None, fetcher=fetcher)
    assert read.status == status


# ── Revisión tras publicar ───────────────────────────────────────────

GOOD = (b'<html><head><title>Guia de SEO local</title><meta name="description" content="Todo sobre SEO local">'
        b'<link rel="canonical" href="https://ejemplo.com/guia/"></head><body><h1>Guia</h1></body></html>')


def test_pagina_publicada_correcta():
    status, checks = publish_check.evaluate(_res(200, body=GOOD, url="https://ejemplo.com/guia"))
    assert status == "ok" and [c["code"] for c in checks] == ["http", "indexable", "canonical", "title",
                                                              "meta_description"]
    assert all(c["ok"] for c in checks)


def test_noindex_por_cabecera_canonical_ajeno_y_sin_textos():
    page = b'<html><head><link rel="canonical" href="https://ejemplo.com/otra"></head><body></body></html>'
    status, checks = publish_check.evaluate(_res(200, body=page, url="https://ejemplo.com/guia",
                                                 headers={"x-robots-tag": "noindex, nofollow"}))
    by_code = {c["code"]: c for c in checks}
    assert status == "problems"
    assert not by_code["indexable"]["ok"] and "X-Robots-Tag" in by_code["indexable"]["detail"]
    assert not by_code["canonical"]["ok"] and "otra URL" in by_code["canonical"]["detail"]
    assert not by_code["title"]["ok"] and not by_code["meta_description"]["ok"]


def test_noindex_por_meta_y_sin_canonical():
    page = b'<html><head><meta name="robots" content="NOINDEX"><title>x</title></head></html>'
    _status, checks = publish_check.evaluate(_res(200, body=page))
    by_code = {c["code"]: c for c in checks}
    assert "meta robots" in by_code["indexable"]["detail"] and not by_code["canonical"]["ok"]


def test_pagina_que_no_responde_bien_no_evalua_lo_demas():
    status, checks = publish_check.evaluate(_res(404, url="https://ejemplo.com/nueva", redirects=1))
    assert status == "problems" and len(checks) == 1 and "404" in checks[0]["detail"]
    assert "redirigir" in checks[0]["detail"]


def test_solo_se_revisan_enlaces_de_la_web_del_cliente():
    assert publish_check.bare_host("https://www.Ejemplo.com/x") == "ejemplo.com"
    assert publish_check.bare_host("sc-domain:ejemplo.com") == "ejemplo.com"
    assert publish_check.bare_host("ejemplo.com") == "ejemplo.com"
    hosts = {"ejemplo.com"}
    assert publish_check.same_site("ejemplo.com", hosts)
    assert publish_check.same_site("blog.ejemplo.com", hosts)
    assert not publish_check.same_site("docs.google.com", hosts)
    assert not publish_check.same_site("otroejemplo.com", hosts)


# ── Jobs ─────────────────────────────────────────────────────────────


def test_jobs_en_el_catalogo_con_locks_propios(monkeypatch):
    from backend.config import settings
    from backend.services.job_catalog import job_definitions

    for flag in ("UPTIME_ENABLED", "WEB_SWEEP_ENABLED", "PUBLISH_CHECK_ENABLED"):
        monkeypatch.setattr(settings, flag, False)
    definitions = {d.spec.key: d for d in job_definitions()}
    health_spec, publish_spec = definitions["web_health"].spec, definitions["publish_checks"].spec
    assert (health_spec.lock_id, health_spec.daily, health_spec.timeout_seconds) == (18, True, 1800)
    assert (publish_spec.lock_id, publish_spec.interval_seconds) == (19, 60)
    locks = [d.spec.lock_id for d in definitions.values()]
    assert len(locks) == len(set(locks)) and 13 not in locks
    assert not definitions["web_health"].enabled and not definitions["publish_checks"].enabled
    monkeypatch.setattr(settings, "WEB_SWEEP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_CHECK_ENABLED", True)
    definitions = {d.spec.key: d for d in job_definitions()}
    assert definitions["web_health"].enabled and definitions["publish_checks"].enabled


async def test_el_job_diario_avisa_si_la_iana_no_responde(monkeypatch):
    from backend.services.job_runtime import JobFailure
    from backend.startup import background_tasks

    async def fake_cycle(_factory):
        return health.HealthResult(hosts=3, bootstrap_failed=True)

    monkeypatch.setattr(health, "run_cycle", fake_cycle)
    with pytest.raises(JobFailure, match="provider_unavailable"):
        await background_tasks._web_health_once()


async def test_el_job_de_publicacion_informa_de_fallos(monkeypatch):
    from backend.services.job_runtime import JobFailure
    from backend.startup import background_tasks

    async def fake_cycle(_factory):
        return publish_check.PublishCycleResult(due=2, failed=1)

    monkeypatch.setattr(publish_check, "run_cycle", fake_cycle)
    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._publish_checks_once()


async def test_sin_red_en_los_tests():
    """El fixture autouse deja ``fetch`` y el certificado sin red."""
    assert (await health.fetch("https://ejemplo.com/")).error == "timeout"
    assert (await health.fetch_tls_certificate("ejemplo.com")).error == "timeout"
    assert (await publish_check.fetch("https://ejemplo.com/")).error == "timeout"


def test_salud_web_fuera_del_journal():
    from backend.db.models import TaskPublishCheck, WebHostExpiry
    from backend.services import change_journal as cj

    for model in (WebHostExpiry, WebRobotsState, TaskPublishCheck):
        assert model not in cj._SPECS
