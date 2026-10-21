"""Extracción (portado de Vigil). Los casos que importan son los de ruido y los de trampa."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.web.extractor import CaptureConfig, extract

FIXTURES = Path(__file__).parent / "fixtures" / "web"
BASE = "https://ejemplo.com/pagina"


def cap(html: str, *, status: int = 200, headers=None, cfg=None, base: str = BASE):
    return extract(html, base_url=base, final_url=base, status_code=status,
                   headers=headers, cfg=cfg)


# --------------------------------------------------------------------------
# La trampa del <title> dentro de un SVG
# --------------------------------------------------------------------------

def test_title_se_lee_del_head_no_del_primer_title_del_documento():
    """fitgeneration.es lleva un <title>WhatsApp</title> dentro del SVG del
    widget de chat. Coger el primer <title> reportaría cambios de title falsos
    en cuanto el cliente toque ese icono."""
    html = """
    <html><head><title>El título bueno</title></head>
    <body><svg><title>WhatsApp</title></svg></body></html>
    """
    assert cap(html).seo["title"] == "El título bueno"


def test_title_ignora_svg_aunque_no_haya_head():
    html = "<html><body><svg><title>WhatsApp</title></svg><p>hola</p></body></html>"
    assert cap(html).seo["title"] == ""


# --------------------------------------------------------------------------
# noindex por cabecera HTTP
# --------------------------------------------------------------------------

def test_noindex_por_cabecera_x_robots_tag_se_detecta():
    """Mirar solo la meta es el fallo clásico: un X-Robots-Tag desindexa igual
    y no aparece en el HTML."""
    html = "<html><head><title>t</title></head><body></body></html>"
    c = cap(html, headers={"X-Robots-Tag": "noindex, nofollow"})
    assert "noindex" in c.seo["robots_directives"]
    assert c.seo["x_robots_tag"] == "noindex, nofollow"


def test_directivas_combinan_meta_y_cabecera():
    html = '<html><head><meta name="robots" content="index, follow"></head><body></body></html>'
    c = cap(html, headers={"X-Robots-Tag": "noarchive"})
    assert set(c.seo["robots_directives"]) == {"index", "follow", "noarchive"}


# --------------------------------------------------------------------------
# Canonical y hreflang
# --------------------------------------------------------------------------

def test_canonical_se_absolutiza():
    html = '<html><head><link rel="canonical" href="/otra-pagina"></head></html>'
    assert cap(html).seo["canonical"] == "https://ejemplo.com/otra-pagina"


def test_canonical_ausente_es_none():
    assert cap("<html><head></head></html>").seo["canonical"] is None


def test_hreflang_ordenado():
    html = """<html><head>
      <link rel="alternate" hreflang="en" href="/en/">
      <link rel="alternate" hreflang="es" href="/es/">
    </head></html>"""
    langs = [h["lang"] for h in cap(html).seo["hreflang"]]
    assert langs == ["en", "es"]


# --------------------------------------------------------------------------
# Schema.org
# --------------------------------------------------------------------------

def test_schema_types_de_json_ld_anidado():
    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Course",
     "provider":{"@type":"Organization","name":"Fit"}}
    </script></head></html>"""
    assert cap(html).seo["schema_types"] == ["Course", "Organization"]


def test_json_ld_roto_no_revienta_la_captura():
    """Un JSON-LD mal formado es habitual. No puede tumbar la página entera."""
    html = """<html><head><title>sigo aquí</title>
    <script type="application/ld+json">{esto no es json,,,}</script>
    </head></html>"""
    c = cap(html)
    assert c.seo["title"] == "sigo aquí"
    assert c.seo["schema_types"] == []


# --------------------------------------------------------------------------
# Supresión de ruido — lo que decide si la herramienta se usa o se ignora
# --------------------------------------------------------------------------

def test_ignore_selectors_quitan_el_banner_de_cookies():
    base = """<html><head><title>t</title></head><body><main>
      <div class="cookie-banner">{banner}</div>
      <p>El contenido de verdad.</p>
    </main></body></html>"""
    cfg = CaptureConfig(ignore_selectors=(".cookie-banner",))
    a = cap(base.format(banner="Acepta las cookies"), cfg=cfg)
    b = cap(base.format(banner="Gestiona tus preferencias"), cfg=cfg)
    assert a.hashes["content"] == b.hashes["content"]


def test_ignore_regexes_neutralizan_una_fecha():
    cfg = CaptureConfig(ignore_regexes=(r"\d{1,2}/\d{1,2}/\d{4}",))
    a = cap("<html><body><main><p>Actualizado 21/07/2026. Texto.</p></main></body></html>", cfg=cfg)
    b = cap("<html><body><main><p>Actualizado 22/07/2026. Texto.</p></main></body></html>", cfg=cfg)
    assert a.hashes["content"] == b.hashes["content"]


def test_regex_invalida_no_revienta():
    cfg = CaptureConfig(ignore_regexes=("[sin-cerrar",))
    assert cap("<html><body><p>hola</p></body></html>", cfg=cfg).text


def test_selector_invalido_no_revienta():
    cfg = CaptureConfig(ignore_selectors=("<<<>>>",))
    assert cap("<html><body><p>hola</p></body></html>", cfg=cfg).text


def test_los_ids_dinamicos_no_cuentan_como_cambio_de_html():
    """React/Vue/Elementor emiten ids numéricos nuevos en cada render."""
    a = cap('<html><body><div id="comp-847362"><p>igual</p></div></body></html>')
    b = cap('<html><body><div id="comp-915284"><p>igual</p></div></body></html>')
    assert a.hashes["html"] == b.hashes["html"]


def test_el_orden_de_los_enlaces_no_cuenta_como_cambio():
    a = cap('<html><body><a href="/a">a</a><a href="/b">b</a></body></html>')
    b = cap('<html><body><a href="/b">b</a><a href="/a">a</a></body></html>')
    assert a.hashes["links"] == b.hashes["links"]


def test_los_parametros_utm_no_cuentan_como_cambio():
    a = cap('<html><body><a href="/x?utm_source=news">x</a></body></html>')
    b = cap('<html><body><a href="/x">x</a></body></html>')
    assert a.hashes["links"] == b.hashes["links"]


def test_un_enlace_que_desaparece_SI_es_cambio():
    """El contrapunto: tanta supresión de ruido no puede tapar lo real."""
    a = cap('<html><body><a href="/a">a</a><a href="/importante">i</a></body></html>')
    b = cap('<html><body><a href="/a">a</a></body></html>')
    assert a.hashes["links"] != b.hashes["links"]
    assert "https://ejemplo.com/importante" in a.links["internal"]
    assert "https://ejemplo.com/importante" not in b.links["internal"]


# --------------------------------------------------------------------------
# Enlaces
# --------------------------------------------------------------------------

def test_internos_y_externos_se_separan_ignorando_www():
    html = """<html><body>
      <a href="https://www.ejemplo.com/interna">1</a>
      <a href="/relativa">2</a>
      <a href="https://otrodominio.com/fuera">3</a>
      <a href="mailto:hola@ejemplo.com">4</a>
      <a href="#ancla">5</a>
    </body></html>"""
    links = cap(html).links
    assert links["internal"] == [
        "https://ejemplo.com/relativa",
        "https://www.ejemplo.com/interna",
    ]
    assert links["external"] == ["https://otrodominio.com/fuera"]


# --------------------------------------------------------------------------
# Detector de render JS
# --------------------------------------------------------------------------

def test_pagina_vacia_con_200_marca_needs_js_render():
    html = '<html><head><title>App</title></head><body><div id="root"></div></body></html>'
    assert cap(html).needs_js_render is True


def test_pagina_con_contenido_no_marca_needs_js_render():
    html = "<html><body><main><p>" + " ".join(["palabra"] * 60) + "</p></main></body></html>"
    assert cap(html).needs_js_render is False


# --------------------------------------------------------------------------
# Estabilidad de los hashes
# --------------------------------------------------------------------------

def test_el_mismo_html_da_el_mismo_hash():
    html = "<html><head><title>t</title></head><body><main><p>hola</p></main></body></html>"
    assert cap(html).hashes == cap(html).hashes


def test_cambiar_el_title_cambia_el_hash_seo_pero_no_el_de_contenido():
    """Base del digest: cada dimensión se mueve por su cuenta."""
    a = cap("<html><head><title>Antes</title></head><body><main><p>igual</p></main></body></html>")
    b = cap("<html><head><title>Después</title></head><body><main><p>igual</p></main></body></html>")
    assert a.hashes["seo"] != b.hashes["seo"]
    assert a.hashes["content"] == b.hashes["content"]


# --------------------------------------------------------------------------
# Contra el HTML REAL de fitgeneration.es
# --------------------------------------------------------------------------

@pytest.mark.skipif(
    not (FIXTURES / "fitgeneration-home.html").exists(),
    reason="falta el fixture de fitgeneration.es",
)
def test_extraccion_sobre_html_real_de_fitgeneration():
    raw = (FIXTURES / "fitgeneration-home.html").read_text(encoding="utf-8", errors="ignore")
    c = extract(
        raw,
        base_url="https://fitgeneration.es/",
        final_url="https://fitgeneration.es/",
        status_code=200,
    )

    # El title del <head>, no el <title>WhatsApp</title> del SVG del widget.
    assert c.seo["title"] == "Fit Generation - La formación del futuro"
    assert "WhatsApp" not in c.seo["title"]

    assert c.seo["canonical"] == "https://fitgeneration.es/"
    assert "index" in c.seo["robots_directives"]
    assert c.seo["h1"], "la home debería tener al menos un H1"
    assert c.seo["word_count"] > 500
    # Server-rendered: no debe pedir Playwright.
    assert c.needs_js_render is False
    assert len(c.links["internal"]) > 10


# --------------------------------------------------------------------------
# Listados: el selector casa con MUCHOS nodos
# --------------------------------------------------------------------------

def test_selector_con_varios_nodos_los_concatena_todos():
    """Bug real encontrado contra fitgeneration.es/blog/: 58 <article> y el
    código cogía el primero (11 palabras de 2.986). Eso marcaba la página como
    "necesita JS" y dejaba 57 tarjetas sin vigilar."""
    html = "<html><body>" + "".join(
        f"<article><h2>Post {i}</h2><p>Resumen del post número {i}.</p></article>"
        for i in range(30)
    ) + "</body></html>"
    c = cap(html)
    assert "Post 0" in c.text
    assert "Post 29" in c.text, "los últimos artículos NO pueden quedarse fuera"
    assert c.seo["word_count"] > 100
    assert c.needs_js_render is False


def test_cambiar_un_articulo_del_final_se_detecta():
    """El contrapunto: si solo miráramos el primer nodo, esto pasaría inadvertido."""
    def listado(ultimo):
        return "<html><body>" + "".join(
            f"<article><p>Post {i}</p></article>" for i in range(9)
        ) + f"<article><p>{ultimo}</p></article></body></html>"

    a = cap(listado("Post 9"))
    b = cap(listado("Post 9 ACTUALIZADO"))
    assert a.hashes["content"] != b.hashes["content"]


def test_content_selector_explicito_tambien_concatena():
    html = """<html><body>
      <div class="card"><p>uno</p></div>
      <div class="card"><p>dos</p></div>
    </body></html>"""
    c = cap(html, cfg=CaptureConfig(content_selector=".card"))
    assert "uno" in c.text and "dos" in c.text


# --------------------------------------------------------------------------
# La poda que cegaba (24-jul-2026)
# --------------------------------------------------------------------------
# David añadió un punto a mano en una card de profesor de /cafyd-online/ y Vigil
# dijo que no había cambios. El culpable era `[aria-live]` en los ignore por
# defecto: Elementor lo pone en cada `.swiper-wrapper` y el tema de Fit
# Generation en cada `.fg-flipcard__inner`, así que las 25 cards se podaban antes
# de calcular ningún hash. No era un falso positivo, que se ve y se corrige: era
# silencio idéntico al de una noche tranquila.

CARD = """<html><body>
  <main>
    <div class="swiper-wrapper" aria-live="polite">
      <div class="fg-flipcard__inner" aria-live="polite">
        <h3>Eneko Baz</h3><p>Doctor en Ciencias del Deporte{extra}</p>
      </div>
    </div>
  </main>
</body></html>"""


def test_los_defaults_no_podan_contenido_marcado_como_aria_live():
    """El caso exacto que se escapó, con los defaults que se envían."""
    from backend.services.web.capture_defaults import DEFAULT_IGNORE_SELECTORS

    cfg = CaptureConfig(ignore_selectors=DEFAULT_IGNORE_SELECTORS)
    antes = cap(CARD.format(extra=""), cfg=cfg)
    despues = cap(CARD.format(extra="."), cfg=cfg)

    assert "Eneko Baz" in antes.text, "la card ni siquiera se está capturando"
    assert antes.hashes["content"] != despues.hashes["content"]
    assert antes.hashes["html"] != despues.hashes["html"]


def test_los_defaults_no_traen_selectores_que_se_coman_contenido():
    """Guardarraíl explícito: estos dos ya cegaron una vez."""
    from backend.services.web.capture_defaults import DEFAULT_IGNORE_SELECTORS

    assert "[aria-live]" not in DEFAULT_IGNORE_SELECTORS
    assert ".carousel" not in DEFAULT_IGNORE_SELECTORS


def test_lo_ignorado_es_invisible_tambien_para_el_html_crudo():
    """Marcar "HTML crudo" NO rescata lo podado, y el copy de la interfaz lo dice.

    Si esto dejara de cumplirse habría que revisar ese copy, no celebrarlo: la
    incoherencia entre dimensiones sería peor que la limitación.
    """
    cfg = CaptureConfig(ignore_selectors=("[aria-live]",))
    antes = cap(CARD.format(extra=""), cfg=cfg)
    despues = cap(CARD.format(extra="."), cfg=cfg)

    assert antes.hashes["content"] == despues.hashes["content"]
    assert antes.hashes["html"] == despues.hashes["html"]


# --------------------------------------------------------------------------
# La sección vigilada acota tres dimensiones, no solo el texto
# --------------------------------------------------------------------------

SECCIONES = """<html><body>
  <main>
    <section class="profes"><p>Ana</p><a href="/ana">Ana</a></section>
    <section class="otros"><p>{fuera}</p><a href="/{fuera}">enlace</a></section>
  </main>
</body></html>"""


def test_la_seccion_vigilada_acota_texto_enlaces_y_html():
    cfg = CaptureConfig(content_selector=".profes")
    a = cap(SECCIONES.format(fuera="uno"), cfg=cfg)
    b = cap(SECCIONES.format(fuera="dos"), cfg=cfg)

    # Un cambio ENTERO fuera de la sección no mueve ninguna de las tres.
    assert a.hashes["content"] == b.hashes["content"]
    assert a.hashes["links"] == b.hashes["links"]
    assert a.hashes["html"] == b.hashes["html"]
    assert a.links["internal"] == ["https://ejemplo.com/ana"]


def test_la_seccion_vigilada_sigue_viendo_lo_de_dentro():
    cfg = CaptureConfig(content_selector=".profes")
    a = cap(SECCIONES.format(fuera="uno"), cfg=cfg)
    b = cap(
        SECCIONES.format(fuera="uno").replace("<p>Ana</p>", "<p>Ana Pérez</p>"),
        cfg=cfg,
    )
    assert a.hashes["content"] != b.hashes["content"]


def test_el_seo_no_se_acota_a_la_seccion():
    """title, canonical y robots viven en el head: acotarlos sería dejar de
    vigilar justo lo que más duele perder."""
    html = """<html><head><title>Antes</title></head>
      <body><section class="profes"><p>Ana</p></section></body></html>"""
    c = cap(html, cfg=CaptureConfig(content_selector=".profes"))
    assert c.seo["title"] == "Antes"


def test_un_selector_que_no_casa_vigila_la_pagina_entera_y_lo_denuncia():
    """Mirar de más son avisos que se leen y se descartan. Mirar de menos es
    silencio indistinguible de la calma, así que se avisa."""
    html = "<html><body><main><p>hola que tal</p></main></body></html>"
    c = cap(html, cfg=CaptureConfig(content_selector=".no-existe"))

    assert c.scope_missed is True
    assert "hola que tal" in c.text


def test_sin_selector_no_hay_aviso_de_seccion_perdida():
    html = "<html><body><main><p>hola</p></main></body></html>"
    assert cap(html).scope_missed is False


def test_los_ignore_tambien_se_aplican_a_los_enlaces():
    """Ignorar el footer debe ignorar también sus enlaces; si no, "ignorar"
    significaría cosas distintas según la dimensión."""
    html = """<html><body>
      <main><a href="/bueno">bueno</a></main>
      <footer><a href="/legal">legal</a></footer>
    </body></html>"""
    c = cap(html, cfg=CaptureConfig(ignore_selectors=("footer",)))
    assert c.links["internal"] == ["https://ejemplo.com/bueno"]
