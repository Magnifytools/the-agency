"""Lectura de sitemaps XML, incluidos índices anidados (portado de Vigil).

Va por `safe_http.fetch` como cualquier otra URL de usuario: un sitemap es una
URL que teclea alguien, así que el riesgo de SSRF es el mismo (y cada sitemap
anidado se revalida igual). Un `.xml.gz` se descomprime con tope de tamaño: un
gzip hostil de pocos KB puede expandirse a gigas.

`lastmod` se ignora a propósito. Es poco fiable en la mayoría de CMS (o siempre
es la fecha de hoy, o no se actualiza nunca) y usarlo para saltarse páginas
haría que Vigil no mirara justo las que sí cambiaron. El barrido es barato:
mejor pedirlas todas.
"""
from __future__ import annotations

import asyncio
import zlib

from lxml import etree

from backend.services.web.safe_http import fetch
from backend.services.web.uptime import cause_label

_MAX_NESTED = 20        # sitemaps hijos a seguir dentro de un índice
_GZ_MAGIC = b"\x1f\x8b"
_MAX_BYTES = 10 * 1024 * 1024        # lo descargado
_MAX_XML_BYTES = 50 * 1024 * 1024    # lo descomprimido
_FETCH_TIMEOUT_S = 20.0
# Toda la importación (índice + anidados) dentro de una petición HTTP.
TOTAL_TIMEOUT_S = 60.0


def _gunzip(data: bytes) -> bytes:
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = inflater.decompress(data, _MAX_XML_BYTES)
    if inflater.unconsumed_tail:
        raise ValueError("el sitemap comprimido es demasiado grande")
    return out


def _parse(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Devuelve (urls, sitemaps_anidados). CPU: llamar con ``asyncio.to_thread``."""
    if xml_bytes[:2] == _GZ_MAGIC:
        xml_bytes = _gunzip(xml_bytes)

    # resolve_entities=False: un sitemap es entrada no confiable y las
    # entidades externas son el vector clásico de XXE.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    if root is None:
        return [], []

    def locs(tag: str) -> list[str]:
        # El namespace varía entre sitemaps; se busca por local-name().
        return [
            (e.text or "").strip()
            for e in root.iter()
            if isinstance(e.tag, str)
            and etree.QName(e).localname == "loc"
            and etree.QName(e.getparent()).localname == tag
        ]

    return locs("url"), locs("sitemap")


async def fetch_sitemap_urls(sitemap_url: str, *, limit: int = 500, user_agent: str | None = None,
                             fetcher=fetch) -> tuple[list[str], bool]:
    """URLs de un sitemap. Devuelve (urls, hay_mas).

    `hay_mas` es True si el sitemap contiene más URLs de las que caben en
    `limit`. Importa devolverlo: sin él, la UI reportaba "200 en el sitemap"
    cuando en realidad había 2.000 y solo se habían cogido las primeras. Quien
    lo lea se queda pensando que ha cubierto el site entero.

    Se piden `limit + 1` justo para poder distinguir "hay exactamente limit" de
    "hay más".
    """
    tope = limit + 1
    pendientes = [sitemap_url]
    vistos: set[str] = set()
    urls: list[str] = []

    while pendientes and len(urls) < tope and len(vistos) < _MAX_NESTED:
        actual = pendientes.pop(0)
        if actual in vistos:
            continue
        vistos.add(actual)

        result = await fetcher(actual, user_agent=user_agent, timeout=_FETCH_TIMEOUT_S,
                               max_bytes=_MAX_BYTES)
        ok = result.error is None and result.status_code is not None and 200 <= result.status_code < 300
        if not ok or not result.body:
            if actual == sitemap_url:
                motivo = cause_label(result.error) if result.error else (
                    f"error HTTP {result.status_code}" if result.status_code else "sin respuesta")
                raise ValueError(motivo or "sin respuesta")
            continue

        try:
            encontrados, anidados = await asyncio.to_thread(_parse, result.body)
        except Exception:
            if actual == sitemap_url:
                raise
            continue

        urls.extend(u for u in encontrados if u.startswith(("http://", "https://")))
        pendientes.extend(anidados)

    # Deduplicar conservando el orden del sitemap.
    unicas = list(dict.fromkeys(urls))
    return unicas[:limit], len(unicas) > limit
