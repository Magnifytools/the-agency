"""Cliente HTTP async endurecido contra SSRF (portado de Vigil: ``safe_http.py`` +
el transport async de ``http_client.py``).

PROBLEMA: validar el host con ``getaddrinfo`` y luego hacer ``httpx.get(url)``
deja una ventana TOCTOU: httpx vuelve a resolver el DNS al conectar, así que un
host malicioso puede devolver una IP pública en la validación y una interna en
la conexión (metadata 169.254.169.254, 10.x, la red privada de Railway
``*.railway.internal`` en fd12::/16…). The Agency pide URLs que teclea una
persona desde su propio servidor: sin esto sería un proxy hacia la red privada.

SOLUCIÓN:
  - resolver el host UNA vez y exigir que TODAS sus IPs sean globales
    (basta una interna para abortar: un DNS hostil haría que se use justo esa);
  - conectar a esa IP fijada (no se vuelve a resolver), conservando la cabecera
    ``Host`` y el SNI/verificación de certificado contra el nombre original
    (``request.extensions["sni_hostname"]``);
  - seguir redirecciones A MANO y revalidar cada salto (un 302 hacia
    169.254.169.254 es el bypass clásico si sólo se valida la URL inicial);
  - sólo http(s) y sólo los puertos 80/443 (añadido de The Agency: una web de
    cliente no vive en el 6379); sin credenciales en la URL;
  - tiempo total acotado y cuerpo leído por streaming con tope de bytes.

La sintaxis se valida al guardar (``check_url_syntax``, sin red) y la URL
entera, DNS incluido, en cada petición (``resolve_url``).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from backend.services.web.headers import browser_headers

MAX_REDIRECTS = 5
MAX_BODY_BYTES = 64 * 1024
ALLOWED_PORTS = frozenset({80, 443})
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_URL_LENGTH = 500
# Nombres que nunca son una web pública, resuelvan a lo que resuelvan.
_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})
_BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".localdomain", ".home.arpa", ".lan", ".intranet")


class SSRFError(ValueError):
    """La URL o su host no supera la validación anti-SSRF."""


class UnresolvableHost(SSRFError):
    """El DNS no devuelve ninguna dirección: para el monitor es una caída (DNS)."""


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # ::ffff:10.0.0.1 es la 10.0.0.1 de toda la vida vestida de IPv6.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url_syntax(url: str) -> str:
    """Valida la forma de la URL sin tocar la red. Devuelve el host (minúsculas).

    Esquema http(s), host con punto, puerto 80/443, sin usuario:contraseña y, si
    el host es una IP literal, que sea pública.
    """
    if not isinstance(url, str) or not url.strip():
        raise SSRFError("URL vacía")
    if len(url) > MAX_URL_LENGTH:
        raise SSRFError("URL demasiado larga")
    try:
        parsed = httpx.URL(url.strip())
    except (httpx.InvalidURL, ValueError) as exc:
        raise SSRFError("URL no válida") from exc
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Esquema no permitido: {parsed.scheme!r}")
    host = (parsed.host or "").lower().rstrip(".")
    if not host:
        raise SSRFError("URL sin host")
    if parsed.userinfo:
        raise SSRFError("La URL no puede llevar usuario ni contraseña")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise SSRFError(f"Puerto no permitido: {port} (sólo 80 y 443)")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise SSRFError(f"IP no pública: {literal}")
        return host
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        raise SSRFError(f"Host interno: {host!r}")
    return host


def resolve_public_ip(hostname: str) -> str:
    """Resuelve ``hostname`` UNA vez y devuelve una IP validada como pública.

    Si CUALQUIER IP resuelta no es global levanta SSRFError. Bloquea: llamar con
    ``asyncio.to_thread`` (lo hace ``resolve_url``).
    """
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnresolvableHost(f"Host no resoluble: {hostname!r}") from exc
    if not infos:
        raise UnresolvableHost(f"Host sin direcciones: {hostname!r}")
    chosen: str | None = None
    for info in infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
        if not _ip_is_public(ip):
            raise SSRFError(f"IP no pública para {hostname!r}: {ip}")
        if chosen is None:
            chosen = str(ip)
    assert chosen is not None  # noqa: S101 — infos no vacío y todas válidas
    return chosen


async def resolve_url(url: str) -> tuple[str, str]:
    """Sintaxis + DNS validado. Devuelve (host, ip fijada)."""
    host = check_url_syntax(url)
    return host, await asyncio.to_thread(resolve_public_ip, host)


class PinnedTransport(httpx.AsyncBaseTransport):
    """Conecta a la IP ya validada, conservando Host y SNI.

    El mapa host→IP lo rellena ``fetch`` justo antes de cada salto, tras validar.
    Si un host no está fijado, falla CERRADO (no conecta).
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, pins: dict[str, str]) -> None:
        self._inner = inner
        self._pins = pins

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").lower().rstrip(".")
        ip = self._pins.get(host)
        if ip is None:
            raise SSRFError(f"Host no fijado (anti-SSRF): {host!r}")
        request.url = request.url.copy_with(host=ip)
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


TransportFactory = Callable[[dict[str, str]], httpx.AsyncBaseTransport]


def default_transport(pins: dict[str, str]) -> httpx.AsyncBaseTransport:
    return PinnedTransport(httpx.AsyncHTTPTransport(retries=0), pins)


@dataclass(frozen=True)
class FetchResult:
    """Lo que devolvió la URL tras seguir sus redirecciones. Nunca lanza.

    ``error`` es un tipo corto cuando no hubo respuesta HTTP final: ``timeout``,
    ``dns``, ``connect`` (rechazada/cortada), ``tls``, ``unsafe`` (la URL o un
    salto apunta a una IP no pública o a un puerto no permitido), ``redirects``
    o ``error``.
    """

    status_code: int | None
    elapsed_ms: int
    final_url: str
    redirects: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    error: str | None = None


def _is_tls_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ssl.SSLError, ssl.CertificateError)):
            return True
        text = str(current).upper()
        if "CERTIFICATE" in text or "SSL" in text or "TLS" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def error_kind(exc: BaseException) -> str:
    if isinstance(exc, UnresolvableHost):
        return "dns"
    if isinstance(exc, SSRFError):
        return "unsafe"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "tls" if _is_tls_error(exc) else "connect"
    if isinstance(exc, httpx.TransportError):
        return "tls" if _is_tls_error(exc) else "connect"
    return "error"


async def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        take = chunk[: max_bytes - total]
        chunks.append(take)
        total += len(take)
        if total >= max_bytes:
            break
    return b"".join(chunks)


async def fetch(
    url: str,
    *,
    user_agent: str | None = None,
    timeout: float = 15.0,
    connect_timeout: float = 10.0,
    max_bytes: int = MAX_BODY_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    transport_factory: TransportFactory | None = None,
) -> FetchResult:
    """Un GET validado y acotado. ``timeout`` es el tiempo TOTAL (todos los saltos)."""
    started = time.perf_counter()
    pins: dict[str, str] = {}
    current = url
    hops = 0

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                transport=(transport_factory or default_transport)(pins),
                timeout=httpx.Timeout(timeout, connect=min(connect_timeout, timeout)),
                follow_redirects=False,
                headers=browser_headers(user_agent),
            ) as client:
                while True:
                    # Revalidar EN CADA SALTO (host, puerto e IP pública fijada).
                    host, ip = await resolve_url(current)
                    pins[host] = ip
                    async with client.stream("GET", current) as resp:
                        location = resp.headers.get("location")
                        if resp.status_code in REDIRECT_CODES and location:
                            if hops >= max_redirects:
                                return FetchResult(resp.status_code, elapsed(), current, hops, error="redirects")
                            current = str(httpx.URL(current).join(location))
                            hops += 1
                            continue
                        body = await _read_capped(resp, max_bytes)
                        return FetchResult(
                            status_code=resp.status_code, elapsed_ms=elapsed(), final_url=current,
                            redirects=hops, headers={k.lower(): v for k, v in resp.headers.items()},
                            body=body,
                        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — una URL nunca tumba el ciclo
        return FetchResult(None, elapsed(), current, hops, error=error_kind(exc))
