"""Extracción normalizada de una página (portado de Vigil).

Todo aquí es CPU pura (lxml, hashes): el barrido lo llama dentro de
``asyncio.to_thread`` para no bloquear el bucle de eventos del servidor.

Cuatro dimensiones, cada una una función pura sobre el árbol ya parseado:

  seo      title, meta description, H1/H2, canonical, robots, hreflang, schema
  content  texto visible, podado y normalizado
  links    enlaces internos/externos, absolutos, ordenados y deduplicados
  html     HTML crudo normalizado (para detectar cambios de maquetación)

`content_selector` acota tres de las cuatro: texto, enlaces y HTML se calculan
sobre esa sección y solo sobre esa. El SEO se queda midiendo la página entera,
porque title, canonical y robots viven en el `<head>` — fuera de cualquier
sección que alguien quiera vigilar — y son justo lo que no puede dejar de
mirarse por acotar el foco.

Todo lo que se compara pasa antes por normalización. Esa es la diferencia entre
una herramienta que se usa y una que se ignora: sin normalizar, un timestamp o
un id de React generan un "cambio" cada noche y el canal de Slack se vuelve
ruido.

Parser: lxml.html. Es lo que ya usa Anvil contra sites de clientes reales,
aguanta HTML roto, y su `drop_tree()` es justo la herramienta para aplicar los
`ignore_selectors`.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from lxml import html as lxml_html

# Nodos que nunca son contenido visible, se poden siempre.
_ALWAYS_DROP = ("script", "style", "noscript", "template", "svg", "iframe")

# Cadena heurística para localizar el cuerpo cuando no hay content_selector.
_CONTENT_FALLBACK = ("main", "article", "[role=main]", ".entry-content", "body")

# Parámetros de tracking que no cambian el destino de un enlace.
_TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z_]+|fbclid|gclid|gbraid|wbraid|msclkid|mc_[a-z]+|_ga|ref|source)$",
    re.I,
)

# Atributos con valores que cambian en cada render (React, Vue, Elementor…).
_VOLATILE_ATTR = re.compile(
    r"^(nonce|integrity|data-reactid|data-react-checksum|data-v-[0-9a-f]+|"
    r"data-elementor-id|csrf[-_]?token)$",
    re.I,
)
_VOLATILE_VALUE = re.compile(r"^[a-z0-9_-]*\d{4,}[a-z0-9_-]*$", re.I)

_WS = re.compile(r"\s+")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INTER_TAG_WS = re.compile(r">\s+<")


@dataclass(frozen=True)
class CaptureConfig:
    """Config efectiva de un watch (ya resuelta watch → cliente)."""

    content_selector: str | None = None
    ignore_selectors: tuple[str, ...] = ()
    ignore_regexes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Capture:
    seo: dict[str, Any]
    text: str
    links: dict[str, list[str]]
    html: str
    hashes: dict[str, str] = field(default_factory=dict)
    # status 200 pero texto casi vacío ⇒ la página probablemente necesita JS.
    needs_js_render: bool = False
    # Hay `content_selector` pero hoy no casa ningún nodo. Se ha vigilado la
    # página entera. Hay que DECIRLO: si el cliente renombra la clase de la
    # sección, el foco se pierde sin que nadie lo note.
    scope_missed: bool = False


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _norm_text(value: str | None) -> str:
    """Normaliza texto para comparar: NFKC, sin zero-width, espacios colapsados."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("​", "").replace("﻿", "").replace("\xa0", " ")
    return _WS.sub(" ", value).strip()


def _abs_url(href: str | None, base: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return None
    try:
        absolute, _ = urldefrag(urljoin(base, href))
    except ValueError:
        return None
    return absolute or None


def _strip_tracking(url: str, extra: tuple[str, ...] = ()) -> str:
    """Quita parámetros de tracking para que no cuenten como cambio de enlace."""
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = []
    for pair in parts.query.split("&"):
        key = pair.split("=", 1)[0]
        if _TRACKING_PARAMS.match(key) or key in extra:
            continue
        kept.append(pair)
    return urlunparse(parts._replace(query="&".join(kept)))


def _registrable(host: str) -> str:
    """Host sin `www.`, en minúsculas. Suficiente para interno/externo."""
    return host.lower().removeprefix("www.")


# ---------------------------------------------------------------------------
# SEO
# ---------------------------------------------------------------------------


def _head_title(tree) -> str:
    """El <title> del <head>, NO el primero del documento.

    fitgeneration.es lleva un `<title>WhatsApp</title>` dentro del SVG del
    widget de chat. Coger el primer <title> del documento haría que Vigil
    reportara un cambio de title falso en cuanto el cliente tocara ese icono.
    """
    nodes = tree.xpath("/html/head/title")
    if not nodes:
        # HTML sin <head> explícito: lxml suele sintetizarlo, pero por si acaso
        # nos quedamos con un <title> que NO esté dentro de un <svg>.
        nodes = [t for t in tree.xpath("//title") if not t.xpath("ancestor::svg")]
    return _norm_text(nodes[0].text_content()) if nodes else ""


def _meta(tree, name: str) -> str:
    nodes = tree.xpath(
        f"//meta[translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        f"'abcdefghijklmnopqrstuvwxyz')='{name}']/@content"
    )
    return _norm_text(nodes[0]) if nodes else ""


def _schema_types(tree) -> list[str]:
    """Tipos @type de los bloques JSON-LD, más itemtype de microdatos.

    Parseo tolerante: un JSON-LD roto es habitual y no debe tumbar la captura
    entera de la página.
    """
    types: set[str] = set()

    for node in tree.xpath("//script[@type='application/ld+json']"):
        raw = (node.text_content() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        def walk(obj):
            if isinstance(obj, dict):
                t = obj.get("@type")
                if isinstance(t, str):
                    types.add(t)
                elif isinstance(t, list):
                    types.update(x for x in t if isinstance(x, str))
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(data)

    for itemtype in tree.xpath("//@itemtype"):
        types.add(str(itemtype).rstrip("/").rsplit("/", 1)[-1])

    return sorted(types)


def extract_seo(tree, *, base_url: str, final_url: str, status_code: int,
                headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (headers or {}).items()}

    canonical_nodes = tree.xpath("//link[@rel='canonical']/@href")
    canonical = _abs_url(canonical_nodes[0], base_url) if canonical_nodes else None

    hreflang = sorted(
        {
            (str(n.get("hreflang")).lower(), _abs_url(n.get("href"), base_url) or "")
            for n in tree.xpath("//link[@rel='alternate'][@hreflang]")
        }
    )

    # El noindex puede venir por meta O por cabecera HTTP. Mirar solo la meta
    # es el fallo clásico: un X-Robots-Tag: noindex desindexa igual y no se ve
    # en el HTML.
    meta_robots = _meta(tree, "robots")
    x_robots = _norm_text(headers.get("x-robots-tag", ""))
    directives = sorted(
        {
            d.strip().lower()
            for d in (meta_robots + "," + x_robots).split(",")
            if d.strip()
        }
    )

    lang_nodes = tree.xpath("/html/@lang")

    return {
        "status_code": status_code,
        "final_url": final_url,
        "title": _head_title(tree),
        "meta_description": _meta(tree, "description"),
        "h1": [_norm_text(n.text_content()) for n in tree.xpath("//h1")],
        "h2": [_norm_text(n.text_content()) for n in tree.xpath("//h2")],
        "canonical": canonical,
        "meta_robots": meta_robots,
        "x_robots_tag": x_robots,
        "robots_directives": directives,
        "hreflang": [{"lang": lg, "href": hr} for lg, hr in hreflang],
        "schema_types": _schema_types(tree),
        "lang": _norm_text(lang_nodes[0]) if lang_nodes else "",
    }


# ---------------------------------------------------------------------------
# Contenido
# ---------------------------------------------------------------------------


def drop_always(tree) -> None:
    """Quita lo que nunca es contenido visible: script, style, svg…

    Público porque la previsualización necesita medir "cuánto texto tiene la
    página" sin contar el JavaScript inline. Sin esto, una página de WordPress
    con 10.000 palabras de scripts diría que se vigila el 40 % de lo que hay, y
    quien lo leyera buscaría un problema que no existe.
    """
    for tag in _ALWAYS_DROP:
        for node in tree.xpath(f"//{tag}"):
            node.drop_tree()


def _prune(tree, selectors: tuple[str, ...]) -> None:
    """Elimina del árbol lo que no debe contar como contenido."""
    drop_always(tree)

    for sel in selectors:
        try:
            nodes = tree.cssselect(sel)
        except Exception:
            # Un selector inválido escrito por un humano no puede reventar el
            # barrido entero: se ignora ese selector y sigue.
            continue
        for node in nodes:
            node.drop_tree()


def _apply_ignore_regexes(text: str, patterns: tuple[str, ...]) -> str:
    """Sustituye por un token en vez de borrar.

    Borrar desplazaría las líneas del diff y haría que un cambio real de al
    lado pareciera otro distinto. El token mantiene la estructura.
    """
    for pattern in patterns:
        try:
            text = re.sub(pattern, "«ignorado»", text)
        except re.error:
            continue
    return text


def _select_all(tree, selector: str) -> list:
    try:
        return tree.cssselect(selector)
    except Exception:
        # Un selector inválido escrito a mano no puede reventar el barrido.
        return []


def scope_nodes(tree, selector: str | None) -> tuple[list, bool]:
    """Los nodos que forman la sección vigilada.

    Devuelve `(nodos, acotado)`. `acotado` es False cuando no hay selector o
    cuando el que hay no casa nada: en ese caso se vigila la página entera, que
    es lo prudente. Un selector que deja de casar (el cliente renombra una clase)
    debe hacer que Vigil mire de más, nunca de menos: mirar de más son avisos
    que se leen y se descartan; mirar de menos es silencio indistinguible de la
    calma.

    Cuando un selector casa con VARIOS nodos se cogen TODOS, no el primero.
    Medido en fitgeneration.es/blog/: la página tiene 58 elementos `<article>`
    (una tarjeta por post). Quedarse con el primero daba 11 palabras en lugar de
    2.986, con dos consecuencias graves:
      * la página se marcaba como "necesita render JS" siendo server-rendered;
      * Vigil vigilaría 1 de 58 tarjetas — un cambio en cualquier otro post
        sería invisible, y publicar uno nuevo parecería reescribir la página.
    Pasa en cualquier listado: blog, categorías, fichas de producto.
    """
    if not selector:
        return [tree], False
    nodes = _select_all(tree, selector)
    return (nodes, True) if nodes else ([tree], False)


def extract_text(nodes: list, cfg: CaptureConfig, *, acotado: bool) -> str:
    """Texto visible, ya podado y normalizado. Los nodos deben venir podados.

    Sin sección acotada se cae a la heurística `main` → `article` → `body`, que
    es lo que evita medir el menú y el pie como si fueran contenido.
    """
    if not acotado:
        raiz = nodes[0]
        for sel in _CONTENT_FALLBACK:
            encontrados = _select_all(raiz, sel)
            if encontrados:
                nodes = encontrados
                break

    text = _norm_text(" ".join(n.text_content() for n in nodes))
    return _apply_ignore_regexes(text, cfg.ignore_regexes)


def extract_links(nodes: list, *, base_url: str) -> dict[str, list[str]]:
    """Enlaces absolutos, sin tracking, deduplicados y ORDENADOS.

    Ordenar es esencial: que un widget de "posts relacionados" baraje el orden
    no es un cambio. Que aparezca o desaparezca un enlace, sí.

    Se leen del árbol YA PODADO y ya acotado a la sección. Si no, "ignorar el
    footer" dejaría de ignorarlo justo aquí y sus 40 enlaces seguirían contando.

    Consecuencia medida en fitgeneration.es/cafyd-online/: de 38 enlaces internos
    se pasa a 1, porque los otros 37 están en el menú y el pie. Es lo que se
    quiere: un cambio de menú aparecería como "37 enlaces perdidos" en TODAS las
    URLs del cliente a la vez, que es justo el ruido por el que `nav`, `header` y
    `footer` están en los ignore por defecto. Quien quiera vigilar el menú, lo
    saca de los ignore en una URL concreta y solo ahí.
    """
    host = _registrable(urlparse(base_url).netloc)
    internal: set[str] = set()
    external: set[str] = set()

    hrefs = [h for n in nodes for h in n.xpath("descendant-or-self::a/@href")]
    for href in hrefs:
        url = _abs_url(str(href), base_url)
        if not url:
            continue
        url = _strip_tracking(url)
        if _registrable(urlparse(url).netloc) == host:
            internal.add(url)
        else:
            external.add(url)

    return {"internal": sorted(internal), "external": sorted(external)}


def normalize_html(raw: str) -> str:
    """HTML crudo normalizado, para el hash de maquetación.

    Sin normalizar atributos volátiles, cualquier framework que emita ids
    numéricos nuevos en cada render produce un "cambio" cada noche.
    """
    text = _COMMENT.sub("", raw)
    text = _INTER_TAG_WS.sub("><", text)
    return _WS.sub(" ", text).strip()


def _strip_volatile_attrs(tree) -> None:
    for node in tree.iter():
        if not hasattr(node, "attrib"):
            continue
        for attr in list(node.attrib):
            value = node.attrib.get(attr) or ""
            if _VOLATILE_ATTR.match(attr) or (
                attr in ("id", "for", "aria-labelledby", "aria-controls")
                and _VOLATILE_VALUE.match(value)
            ):
                del node.attrib[attr]


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

# Por debajo de esto, con un 200, sospechamos render por JS.
_MIN_WORDS_FOR_HTML_RENDER = 25


def parse(raw_html: str):
    """Árbol lxml de un HTML posiblemente vacío o roto."""
    return lxml_html.fromstring(raw_html if raw_html.strip() else "<html></html>")


def prepare(tree, cfg: CaptureConfig) -> tuple[list, bool]:
    """Poda, limpia atributos volátiles y acota a la sección.

    Es la secuencia exacta que aplica el barrido, y existe como función pública
    para que la previsualización de la interfaz pueda enseñar lo que se vigilaría
    DE VERDAD. Una previsualización que reimplemente estos tres pasos acabaría
    divergiendo del barrido y mentiría justo cuando más se confía en ella.
    """
    _prune(tree, cfg.ignore_selectors)
    _strip_volatile_attrs(tree)
    return scope_nodes(tree, cfg.content_selector)


def extract(raw_html: str, *, base_url: str, final_url: str, status_code: int,
            headers: dict[str, str] | None = None,
            cfg: CaptureConfig | None = None) -> Capture:
    cfg = cfg or CaptureConfig()

    tree = parse(raw_html)

    # El SEO se extrae ANTES de podar: canonical, hreflang y JSON-LD viven en
    # el <head> o en <script>, que están en la lista de poda.
    seo = extract_seo(
        tree, base_url=base_url, final_url=final_url,
        status_code=status_code, headers=headers,
    )

    # A partir de aquí el árbol se poda y se acota. Las tres dimensiones
    # restantes miran EXACTAMENTE lo mismo: si algo se ignora, se ignora en las
    # tres, y si se acota una sección, las tres se acotan a ella. Que "HTML
    # crudo" viera lo que "texto" no ve sería una trampa: el flag suena a
    # "vigílalo todo" y no lo sería.
    nodes, acotado = prepare(tree, cfg)

    text = extract_text(nodes, cfg, acotado=acotado)
    links = extract_links(nodes, base_url=base_url)

    word_count = len(text.split())
    seo["word_count"] = word_count

    html_norm = normalize_html(
        "".join(
            lxml_html.tostring(n, encoding="unicode", method="html") for n in nodes
        )
    )

    hashes = {
        "seo": sha256(json.dumps(seo, sort_keys=True, ensure_ascii=False)),
        "content": sha256(text),
        "links": sha256(json.dumps(links, sort_keys=True, ensure_ascii=False)),
        "html": sha256(html_norm),
    }

    return Capture(
        seo=seo,
        text=text,
        links=links,
        html=html_norm,
        hashes=hashes,
        needs_js_render=(status_code == 200 and word_count < _MIN_WORDS_FOR_HTML_RENDER),
        scope_missed=bool(cfg.content_selector) and not acotado,
    )
