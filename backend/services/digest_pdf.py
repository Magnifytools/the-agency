"""PDF del resumen (digest) para el cliente.

Es lo mismo que recibe el cliente por email (``render_email``): saludo, periodo,
secciones hecho/necesito/próximo, bloques de Search Console y GA4 pintados con
código (con los interruptores ``include_seo`` / ``include_ga4``) y cierre. Se
monta con fpdf2 a partir de los MISMOS datos y helpers que el email, no
convirtiendo el HTML: fpdf2 ya estaba en ``requirements.txt`` (propuestas),
es Python puro y no necesita paquetes de sistema en ``python:3.12-slim``.

Sin red: no se carga ninguna imagen ni fuente externa. El logo es vectorial y
la letra es Helvetica de serie (cp1252). ``_OfflinePDF.image`` rechaza
cualquier imagen, así que ni un ``<img src="http://…">`` colado en el cierre ni
un cambio futuro pueden hacer que el servidor pida una URL al generar el PDF.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from calendar import monthrange
from datetime import date
from html.parser import HTMLParser

from fpdf import FPDF

from backend.db.models import DigestTone, WeeklyDigest
from backend.schemas.digest import DigestContent, DigestItem
from backend.services import digest_ga4, digest_seo
from backend.services.digest_renderer import (
    _SECTION_COLORS,
    _date_text,
    _ga4_block,
    _section_titles,
    _seo_block,
)

# Paleta del email (digest_renderer): amarillo Magnify, casi negro y grises.
_BRAND = (0xFF, 0xD6, 0x00)
_DARK = (0x0A, 0x0A, 0x0A)
_GRAY = (0x66, 0x66, 0x66)
_LIGHT_GRAY = (0x99, 0x99, 0x99)
_BORDER = (0xE8, 0xE8, 0xE5)
_GREEN, _RED = (0x15, 0x80, 0x3D), (0xB9, 0x1C, 0x1C)

_MARGIN_X, _MARGIN_TOP, _MARGIN_BOTTOM = 20, 18, 22
_FONT = "Helvetica"
_SAFE_LINK = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)

# Caracteres habituales fuera de cp1252 (la codificación de Helvetica de serie).
_REPLACEMENTS = {
    "−": "-", "→": "->", "←": "<-", " ": " ", " ": " ",
    " ": " ", "​": "", "‑": "-", "‐": "-",
}


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def clean_text(text: str | None) -> str:
    """Texto imprimible con Helvetica (cp1252). Lo que no cabe (emojis…) se quita."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    out = []
    for char in text:
        try:
            char.encode("cp1252")
        except UnicodeEncodeError:
            continue
        out.append(char)
    return re.sub(r"[ \t]{2,}", " ", "".join(out))


class _OfflinePDF(FPDF):
    """FPDF que nunca carga imágenes: fpdf2 descarga con urlopen si recibe una URL."""

    def __init__(self, client_name: str) -> None:
        super().__init__(unit="mm", format="A4")
        self.core_fonts_encoding = "windows-1252"
        self.client_name = client_name

    def image(self, *args, **kwargs):  # noqa: D401 - bloqueo explícito
        raise RuntimeError("El PDF del resumen no admite imágenes externas")

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*_BORDER)
        self.set_line_width(0.2)
        self.line(_MARGIN_X, self.get_y(), self.w - _MARGIN_X, self.get_y())
        self.ln(2)
        self.set_font(_FONT, "", 8)
        self.set_text_color(*_LIGHT_GRAY)
        self.cell(0, 4, "magnify.ing", link="https://www.magnify.ing")
        self.set_x(_MARGIN_X)
        self.cell(0, 4, f"Página {self.page_no()} de {{nb}}", align="R")


# ---------------------------------------------------------------------------
# Cierre: admite HTML (enlaces tipo Google Sheets). Se reduce a texto, saltos,
# negritas y enlaces http(s)/mailto. Nada de imágenes, estilos ni scripts.
# ---------------------------------------------------------------------------

class _ClosingParser(HTMLParser):
    _BLOCK = {"p", "div", "ul", "ol", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.runs: list[tuple[str, bool, str]] = []
        self._bold = 0
        self._links: list[str] = []
        self._skip = 0

    def _add(self, text: str) -> None:
        if self._skip or not text:
            return
        link = next((href for href in reversed(self._links) if href), "")
        self.runs.append((text, self._bold > 0, link))

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"b", "strong"}:
            self._bold += 1
        elif tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            self._links.append(href if _SAFE_LINK.match(href) else "")
        elif tag == "br":
            self._add("\n")
        elif tag == "li":
            self._add("\n• ")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag in {"b", "strong"}:
            self._bold = max(0, self._bold - 1)
        elif tag == "a" and self._links:
            self._links.pop()
        elif tag in self._BLOCK:
            self._add("\n")

    def handle_data(self, data):
        self._add(data)


def closing_runs(closing: str) -> list[tuple[str, bool, str]]:
    """(texto, negrita, enlace) del cierre, igual que el email: \\n es salto de línea."""
    parser = _ClosingParser()
    parser.feed((closing or "").replace("\r\n", "\n"))
    parser.close()
    runs = [(clean_text(text), bold, link) for text, bold, link in parser.runs]
    return [run for run in runs if run[0]]


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------

def _logo(pdf: FPDF, x: float, y: float, size: float = 8) -> None:
    """La marca de Magnify (la del favicon de la app) en vectorial: sin descargas."""
    pdf.set_fill_color(*_DARK)
    pdf.rect(x, y, size, size, style="F", round_corners=True, corner_radius=size * 0.2)
    s = size / 100
    pdf.set_fill_color(*_BRAND)
    outer = [(50, 18), (74, 80), (65, 80), (59, 63), (41, 63), (35, 80), (26, 80)]
    pdf.polygon([(x + px * s, y + py * s) for px, py in outer], style="F")
    pdf.set_fill_color(*_DARK)
    pdf.polygon([(x + px * s, y + py * s) for px, py in ((50, 32), (43, 56), (57, 56))], style="F")


def _ensure_space(pdf: FPDF, height: float) -> None:
    if pdf.will_page_break(height):
        pdf.add_page()


def _header(pdf: _OfflinePDF, date_text: str, greeting: str) -> None:
    top = pdf.get_y()
    _logo(pdf, _MARGIN_X, top)
    pdf.set_xy(_MARGIN_X + 10, top + 1.2)
    pdf.set_font(_FONT, "B", 13)
    pdf.set_text_color(*_DARK)
    pdf.cell(40, 6, "Magnify", link="https://www.magnify.ing")
    if pdf.client_name:
        pdf.set_xy(_MARGIN_X + 50, top + 1.6)
        pdf.set_font(_FONT, "", 9)
        pdf.set_text_color(*_GRAY)
        pdf.cell(pdf.epw - 50, 5, clean_text(pdf.client_name), align="R")
    pdf.set_xy(_MARGIN_X, top + 14)
    if date_text:
        pdf.set_font(_FONT, "B", 8.5)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(0, 4.5, clean_text(date_text).upper(), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.5)
    if greeting:
        pdf.set_font(_FONT, "B", 14)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(0, 6.5, clean_text(greeting), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    # La raya amarilla de 3 px del email.
    pdf.set_fill_color(*_BRAND)
    pdf.rect(_MARGIN_X, pdf.get_y(), pdf.epw, 1, style="F")
    pdf.ln(3)


def _lines(pdf: FPDF, text: str, style: str, size: float) -> int:
    # Se mide en un documento aparte: un dry_run sobre el real le cambia la
    # fuente "en curso" sin escribirla y la siguiente set_font no se emite.
    ruler = getattr(pdf, "_ruler", None)
    if ruler is None:
        ruler = FPDF(unit="mm", format="A4")
        ruler.core_fonts_encoding = "windows-1252"
        ruler.set_margins(_MARGIN_X, _MARGIN_TOP, _MARGIN_X)
        ruler.add_page()
        pdf._ruler = ruler
    ruler.set_font(_FONT, style, size)
    return len(ruler.multi_cell(0, 5, clean_text(text), align="L", dry_run=True, output="LINES"))


def _item_height(pdf: FPDF, item: DigestItem) -> float:
    height = 2 + 5.2 * _lines(pdf, item.title, "B", 10.5) + 2.2
    if item.description:
        height += 0.8 + 5 * _lines(pdf, item.description, "", 10)
    return height


def _section(pdf: FPDF, title: str, items: list[DigestItem], color: str) -> None:
    if not items:
        return
    pdf.ln(5)
    # El título no se queda solo al pie: con él baja al menos el primer elemento.
    _ensure_space(pdf, 10 + _item_height(pdf, items[0]))
    y = pdf.get_y()
    pdf.set_fill_color(*_hex(color))
    # fpdf2 2.8 sitúa el círculo por su centro.
    pdf.circle(_MARGIN_X + 1.6, y + 3.2, 1.6, style="F")
    pdf.set_xy(_MARGIN_X + 5.5, y)
    pdf.set_font(_FONT, "B", 12)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 6.4, clean_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    for item in items:
        # Un elemento no se parte entre dos páginas (salvo que no quepa en una).
        _ensure_space(pdf, min(_item_height(pdf, item), pdf.eph - 10))
        pdf.ln(2)
        pdf.set_font(_FONT, "B", 10.5)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(0, 5.2, clean_text(item.title), align="L", new_x="LMARGIN", new_y="NEXT")
        if item.description:
            pdf.ln(0.8)
            pdf.set_font(_FONT, "", 10)
            pdf.set_text_color(*_GRAY)
            pdf.multi_cell(0, 5, clean_text(item.description), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.2)
        pdf.set_draw_color(*_BORDER)
        pdf.set_line_width(0.25)
        pdf.line(_MARGIN_X, pdf.get_y(), pdf.w - _MARGIN_X, pdf.get_y())


def _change_cell(pdf: FPDF, x: float, y: float, w: float, h: float, text: str, sign: int) -> None:
    """Celda de cambio con el color del email; ▲/▼ se dibujan (no están en Helvetica)."""
    color = _GREEN if sign > 0 else _RED if sign < 0 else _GRAY
    pdf.set_text_color(*color)
    pdf.set_font(_FONT, "B", 10)
    arrow = text[:1] if text[:1] in {"▲", "▼"} else ""
    body = clean_text(text[1:].strip() if arrow else text)
    pdf.set_xy(x, y)
    pdf.cell(w, h, body, align="R")
    if arrow:
        right = x + w - pdf.c_margin - pdf.get_string_width(body) - 1.2
        mid, half = y + h / 2, 1.2
        pdf.set_fill_color(*color)
        points = ([(right - 2 * half, mid + half), (right, mid + half), (right - half, mid - half)]
                  if arrow == "▲" else
                  [(right - 2 * half, mid - half), (right, mid - half), (right - half, mid + half)])
        pdf.polygon(points, style="F")


def _metrics_block(pdf: FPDF, *, title: str, headline: str, month_label: str,
                   previous_label: str | None, rows: list[dict], extra: str | None, source: str) -> None:
    pdf.ln(6)
    _ensure_space(pdf, 30 + 7.5 * len(rows))
    pdf.set_font(_FONT, "B", 12)
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(0, 6.4, clean_text(title), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font(_FONT, "", 10)
    pdf.set_text_color(*_GRAY)
    pdf.multi_cell(0, 5, clean_text(headline), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    label_w = pdf.epw * 0.4
    col_w = (pdf.epw - label_w) / (3 if previous_label else 1)
    pdf.set_font(_FONT, "", 8.5)
    pdf.set_text_color(*_GRAY)
    pdf.cell(label_w, 6, "")
    pdf.cell(col_w, 6, clean_text(month_label), align="R")
    if previous_label:
        pdf.cell(col_w, 6, clean_text(previous_label), align="R")
        pdf.cell(col_w, 6, "Cambio", align="R")
    pdf.ln(6)
    for row in rows:
        y = pdf.get_y()
        pdf.set_draw_color(*_BORDER)
        pdf.set_line_width(0.25)
        pdf.line(_MARGIN_X, y, pdf.w - _MARGIN_X, y)
        pdf.set_xy(_MARGIN_X, y)
        pdf.set_font(_FONT, "", 10)
        pdf.set_text_color(*_DARK)
        pdf.cell(label_w, 7.5, clean_text(row["label"]))
        pdf.set_font(_FONT, "B", 10)
        pdf.cell(col_w, 7.5, clean_text(row["current"]), align="R")
        if previous_label:
            pdf.set_font(_FONT, "", 10)
            pdf.set_text_color(*_GRAY)
            pdf.cell(col_w, 7.5, clean_text(row["previous"]), align="R")
            _change_cell(pdf, _MARGIN_X + label_w + 2 * col_w, y, col_w, 7.5, row["change"], row["sign"])
        pdf.set_xy(_MARGIN_X, y + 7.5)
    if extra:
        pdf.ln(2)
        pdf.set_font(_FONT, "", 9.5)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(0, 4.8, clean_text(extra), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.set_font(_FONT, "", 8.5)
    pdf.set_text_color(*_LIGHT_GRAY)
    pdf.cell(0, 4.5, source, new_x="LMARGIN", new_y="NEXT")


def _seo(pdf: FPDF, seo: dict) -> None:
    previous = digest_seo._month_of(seo["previous"]).capitalize() if seo.get("previous") else None
    _metrics_block(pdf, title=digest_seo.title(seo), headline=digest_seo.headline(seo),
                   month_label=digest_seo._month_of(seo["month"]).capitalize(), previous_label=previous,
                   rows=digest_seo.rows(seo), extra=digest_seo.year_ago_line(seo),
                   source="Fuente: Google Search Console.")


def _ga4(pdf: FPDF, ga4: dict) -> None:
    previous = digest_seo._month_of(ga4["previous"]).capitalize() if ga4.get("previous") else None
    _metrics_block(pdf, title=digest_ga4.title(ga4), headline=digest_ga4.headline(ga4),
                   month_label=digest_seo._month_of(ga4["month"]).capitalize(), previous_label=previous,
                   rows=digest_ga4.rows(ga4), extra=None, source="Fuente: Google Analytics 4.")


def _closing(pdf: FPDF, closing: str) -> None:
    runs = closing_runs(closing)
    if not runs:
        return
    pdf.ln(8)
    _ensure_space(pdf, 12)
    pdf.set_x(_MARGIN_X)
    for text, bold, link in runs:
        if link:
            pdf.set_font(_FONT, "BU" if bold else "U", 10.5)
            pdf.set_text_color(*_DARK)
        else:
            pdf.set_font(_FONT, "B" if bold else "", 10.5)
            pdf.set_text_color(*_DARK)
        pdf.write(5.6, text, link=link)


# ---------------------------------------------------------------------------
# API del módulo
# ---------------------------------------------------------------------------

def render_pdf(
    content: DigestContent,
    *,
    client_name: str = "",
    tone: DigestTone | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    seo: dict | None = None,
    ga4: dict | None = None,
) -> bytes:
    """Los bytes del PDF A4. Mismo contenido y mismas reglas que ``render_email``."""
    titles = _section_titles(tone)
    pdf = _OfflinePDF(client_name)
    pdf.set_margins(_MARGIN_X, _MARGIN_TOP, _MARGIN_X)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_BOTTOM)
    pdf.alias_nb_pages()
    pdf.set_title(clean_text(f"Resumen {client_name} · {_date_text(content, period_start, period_end)}".strip()))
    pdf.set_author("Magnify")
    pdf.set_creator("The Agency")
    pdf.set_lang("es-ES")
    pdf.add_page()

    _header(pdf, _date_text(content, period_start, period_end), content.greeting)
    _section(pdf, titles["done"], content.sections.done, _SECTION_COLORS["done"])
    _section(pdf, titles["need"], content.sections.need, _SECTION_COLORS["need"])
    _section(pdf, titles["next"], content.sections.next, _SECTION_COLORS["next"])
    seo_block = _seo_block(content, seo)
    if seo_block:
        _seo(pdf, seo_block)
    ga4_block = _ga4_block(content, ga4)
    if ga4_block:
        _ga4(pdf, ga4_block)
    _closing(pdf, content.closing)
    return bytes(pdf.output())


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60]


def pdf_filename(client_name: str | None, period_start: date | None, period_end: date | None,
                 digest_id: int) -> str:
    """informe-<cliente>-<periodo>.pdf (ASCII: va tal cual en Content-Disposition)."""
    if period_start and period_end:
        whole_month = (period_start.day == 1 and period_start.year == period_end.year
                       and period_start.month == period_end.month
                       and period_end.day == monthrange(period_end.year, period_end.month)[1])
        period = (period_start.strftime("%Y-%m") if whole_month
                  else f"{period_start.isoformat()}_{period_end.isoformat()}")
    else:
        period = str(digest_id)
    parts = ["informe", _slug(client_name or "") or "cliente", period]
    return "-".join(parts) + ".pdf"


# Generar un PDF es CPU: fuera del bucle de eventos y con techo de tiempo. Un
# resumen normal tarda decenas de milisegundos; 20 s sólo lo agota algo anómalo.
PDF_TIMEOUT_SECONDS = 20


async def digest_pdf(digest: WeeklyDigest, client_name: str) -> tuple[bytes, str]:
    """(bytes, nombre de fichero) del resumen guardado. ValueError si no tiene contenido válido."""
    if not digest.content:
        raise ValueError("El resumen no tiene contenido")
    content = DigestContent(**digest.content)
    raw = digest.raw_context or {}
    data = await asyncio.wait_for(
        asyncio.to_thread(
            render_pdf, content, client_name=client_name, tone=digest.tone,
            period_start=digest.period_start, period_end=digest.period_end,
            seo=raw.get("seo"), ga4=raw.get("ga4"),
        ),
        timeout=PDF_TIMEOUT_SECONDS,
    )
    return data, pdf_filename(client_name, digest.period_start, digest.period_end, digest.id)
