"""Bloque de Search Console de los resúmenes mensuales.

Se calcula y se pinta con código, no lo redacta la IA: el cliente ve
exactamente las cifras guardadas en `gsc_daily`. El bloque sólo existe cuando
`raw_context["seo"]["status"] == "ok"` y el contenido no lo ha desactivado.

Si además llega `seo["detail"]` (la foto del mes de `digest_seo_detail`: top de
búsquedas y páginas, oportunidades y marca), se pinta debajo de los totales.
"""

from __future__ import annotations

from datetime import date

from backend.services.digest_periods import format_month


def _int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _dec(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _month_of(period: dict) -> str:
    return format_month(date.fromisoformat(period["start"])).split(" de ")[0]


def is_available(seo: dict | None) -> bool:
    return bool(seo) and seo.get("status") == "ok"


def headline(seo: dict) -> str:
    """Frase de lectura, calculada: 'En septiembre llegaron 1.234 visitas…'."""
    month = seo["month"]
    text = f"En {_month_of(month)}, Google trajo {_int(month['clicks'])} visitas orgánicas a la web"
    change = (seo.get("vs_previous") or {}).get("clicks_pct")
    if change is None:
        return text + "."
    previous = _month_of(seo["previous"])
    if abs(change) < 0.5:
        return text + f", prácticamente las mismas que en {previous}."
    direction = "más" if change > 0 else "menos"
    return text + f", un {_dec(abs(change))} % {direction} que en {previous}."


def _change(value: float | None, *, unit: str) -> tuple[str, int]:
    """(texto, signo) con signo 1 = mejora, -1 = empeora, 0 = neutro."""
    if value is None:
        return "—", 0
    sign = 1 if value > 0 else -1 if value < 0 else 0
    if unit == "%":
        return f"{'+' if value > 0 else ''}{_dec(value)} %", sign
    if unit == "pp":
        return f"{'+' if value > 0 else ''}{_dec(value, 2)} p. p.", sign
    # Posición: el delta ya viene con positivo = mejora.
    return ("▲ " if value > 0 else "▼ " if value < 0 else "") + _dec(abs(value)), sign


def rows(seo: dict) -> list[dict]:
    month, previous = seo["month"], seo.get("previous") or {}
    changes = seo.get("vs_previous") or {}

    def fmt(period: dict, key: str) -> str:
        value = period.get(key)
        if value is None:
            return "—"
        if key == "ctr":
            return f"{_dec(value, 2)} %"
        if key == "position":
            return _dec(value)
        return _int(value)

    out = []
    for key, label, change_key, unit in (
        ("clicks", "Clics", "clicks_pct", "%"),
        ("impressions", "Impresiones", "impressions_pct", "%"),
        ("ctr", "CTR", "ctr_delta", "pp"),
        ("position", "Posición media", "position_delta", "pos"),
    ):
        change_text, sign = _change(changes.get(change_key) if change_key else None, unit=unit)
        out.append({"label": label, "current": fmt(month, key), "previous": fmt(previous, key),
                    "change": change_text, "sign": sign})
    return out


def year_ago_line(seo: dict) -> str | None:
    """El mismo mes del año anterior, con las cuatro cifras que haya."""
    changes = seo.get("vs_year_ago") or {}
    if not seo.get("year_ago"):
        return None
    parts = []
    for key, label, unit in (("clicks_pct", "clics", "%"), ("impressions_pct", "impresiones", "%"),
                             ("ctr_delta", "CTR", "pp"), ("position_delta", "posición media", "pos")):
        value = changes.get(key)
        if value is None:
            continue
        if unit == "pos":
            # En palabras: en una frase la flecha no se lee (y el PDF no la tiene).
            moved = _dec(abs(value))
            parts.append(f"{label} igual" if value == 0
                         else f"{label} {'mejora' if value > 0 else 'empeora'} {moved} puestos")
        else:
            parts.append(f"{label} {_change(value, unit=unit)[0]}")
    if not parts:
        return None
    month = format_month(date.fromisoformat(seo["year_ago"]["start"]))
    return f"Respecto a {month}: {', '.join(parts)}."


# ── Detalle del mes (top, oportunidades y marca) ─────────────────────


def detail_of(seo: dict) -> dict | None:
    detail = seo.get("detail")
    return detail if detail and detail.get("status") == "ok" else None


def _row_change(row: dict) -> tuple[str, int]:
    if row.get("is_new"):
        return "nueva", 1
    return _change(row.get("clicks_pct"), unit="%")


def _position(value: float | None) -> str:
    return "—" if value is None else _dec(value)


QUERIES_TITLE = "Búsquedas que más visitas trajeron"
PAGES_TITLE = "Páginas con más visitas desde Google"
OPPORTUNITIES_TITLE = "Oportunidades: búsquedas cerca de la primera página"
OPPORTUNITIES_NOTE = ("Aparecen entre la posición 8 y la 20 con bastantes impresiones: "
                      "con poco trabajo pueden empezar a traer visitas.")
BRAND_TITLE = "Con la marca y sin ella"
BRAND_NOTE = ("Las búsquedas sin la marca son las de quien todavía no os conoce: "
              "es lo que el SEO hace crecer.")


def detail_rows(rows: list[dict], *, label_key: str = "key") -> list[dict]:
    """Filas listas para pintar: etiqueta, clics, posición y cambio de clics."""
    out = []
    for row in rows:
        change, sign = _row_change(row)
        out.append({"label": row.get(label_key) or row["key"], "url": row["key"] if label_key == "label" else None,
                    "clicks": _int(row["clicks"]), "position": _position(row.get("position")),
                    "change": change, "sign": sign})
    return out


def opportunity_rows(detail: dict) -> list[dict]:
    return [{"label": row["key"], "impressions": _int(row["impressions"]),
             "position": _position(row["position"])} for row in detail.get("opportunities") or []]


def brand_rows(detail: dict) -> list[dict]:
    brand = detail.get("brand")
    if not brand:
        return []
    rows = []
    for key, label, change_key in (("non_brand", "Sin la marca", "non_brand_pct"),
                                   ("brand", "Con la marca", "brand_pct")):
        change, sign = _change(brand.get(change_key), unit="%")
        rows.append({"label": label, "clicks": _int(brand[key]), "change": change, "sign": sign})
    if brand.get("unclassified"):
        rows.append({"label": "Sin detallar por Google", "clicks": _int(brand["unclassified"]),
                     "change": "", "sign": 0})
    return rows


def render_detail_text(detail: dict, *, bold: str = "") -> list[str]:
    compare = bool(detail.get("previous"))
    lines: list[str] = []
    for title_text, rows in ((QUERIES_TITLE, detail_rows(detail.get("queries") or [])),
                             (PAGES_TITLE, detail_rows(detail.get("pages") or [], label_key="label"))):
        if not rows:
            continue
        lines.append(f"{bold}{title_text}{bold}")
        for index, row in enumerate(rows, 1):
            change = f"; {row['change']}" if compare else ""
            lines.append(f"  {index}. {row['label']}: {row['clicks']} clics (posición {row['position']}{change})")
    opportunities = opportunity_rows(detail)
    if opportunities:
        lines.append(f"{bold}{OPPORTUNITIES_TITLE}{bold}")
        lines.extend(f"  - {row['label']}: posición {row['position']}, {row['impressions']} impresiones"
                     for row in opportunities)
    brand = brand_rows(detail)
    if brand:
        lines.append(f"{bold}{BRAND_TITLE}{bold}")
        for row in brand:
            change = f" ({row['change']})" if compare and row["change"] else ""
            lines.append(f"  - {row['label']}: {row['clicks']} clics{change}")
    return lines


def title(seo: dict) -> str:
    return f"Visibilidad en Google · {format_month(date.fromisoformat(seo['month']['start']))}"


def render_text(seo: dict, *, bold: str = "") -> list[str]:
    """Líneas para texto plano, Slack (bold='*') o Discord (bold='**')."""
    previous_month = _month_of(seo["previous"]) if seo.get("previous") else None
    lines = [f"{bold}{title(seo)}{bold}", headline(seo)]
    for row in rows(seo):
        detail = f"{row['current']}"
        if previous_month:
            detail += f" (en {previous_month}: {row['previous']}; {row['change']})"
        lines.append(f"  - {row['label']}: {detail}")
    extra = year_ago_line(seo)
    if extra:
        lines.append(extra)
    detail = detail_of(seo)
    if detail:
        lines.extend(render_detail_text(detail, bold=bold))
    lines.append("Fuente: Google Search Console.")
    return lines


_GREEN, _RED, _NEUTRAL = "#15803D", "#B91C1C", "#666666"


def _detail_table_html(head: list[str], rows: list[list[tuple[str, str]]], *, gray: str, border: str) -> str:
    """Tabla compacta: la primera columna a la izquierda y el resto a la derecha.
    Cada celda es (html ya escapado, color)."""
    head_html = "".join(
        f'<td style="padding:4px 0;font-size:12px;color:{gray};text-align:{"left" if i == 0 else "right"};">{h}</td>'
        for i, h in enumerate(head))
    body = ""
    for row in rows:
        cells = ""
        for i, (value, color) in enumerate(row):
            align = "left" if i == 0 else "right"
            weight = "600" if i == 1 else "400"
            pad = "padding:6px 8px 6px 0;" if i == 0 else "padding:6px 0 6px 8px;white-space:nowrap;"
            cells += (f'<td style="{pad}border-top:1px solid {border};font-size:13px;color:{color};'
                      f'text-align:{align};font-weight:{weight};word-break:break-word;">{value}</td>')
        body += f"<tr>{cells}</tr>"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f"<tr>{head_html}</tr>{body}</table>")


def _subtitle_html(text: str, note: str | None, *, esc, dark: str, gray: str) -> str:
    html = f'<p style="margin:18px 0 6px 0;font-size:14px;font-weight:700;color:{dark};">{esc(text)}</p>'
    if note:
        html += f'<p style="margin:0 0 6px 0;font-size:12px;color:{gray};line-height:1.5;">{esc(note)}</p>'
    return html


def render_detail_html(detail: dict, *, esc, dark: str, gray: str, border: str) -> str:
    compare = bool(detail.get("previous"))
    previous = _month_of(detail["previous"]) if compare else None
    change_head = f"Frente a {previous}" if previous else None
    html = ""
    for title_text, rows in ((QUERIES_TITLE, detail_rows(detail.get("queries") or [])),
                             (PAGES_TITLE, detail_rows(detail.get("pages") or [], label_key="label"))):
        if not rows:
            continue
        head = ["", "Clics", "Posición"] + ([change_head] if change_head else [])
        table_rows = []
        for row in rows:
            label = esc(row["label"])
            if row["url"] and row["url"].startswith(("http://", "https://")):
                label = (f'<a href="{esc(row["url"])}" target="_blank" '
                         f'style="color:{dark};text-decoration:underline;">{label}</a>')
            cells = [(label, dark), (esc(row["clicks"]), dark), (esc(row["position"]), gray)]
            if change_head:
                color = _GREEN if row["sign"] > 0 else _RED if row["sign"] < 0 else _NEUTRAL
                cells.append((esc(row["change"]), color))
            table_rows.append(cells)
        html += _subtitle_html(title_text, None, esc=esc, dark=dark, gray=gray)
        html += _detail_table_html(head, table_rows, gray=gray, border=border)
    opportunities = opportunity_rows(detail)
    if opportunities:
        html += _subtitle_html(OPPORTUNITIES_TITLE, OPPORTUNITIES_NOTE, esc=esc, dark=dark, gray=gray)
        html += _detail_table_html(
            ["", "Impresiones", "Posición"],
            [[(esc(r["label"]), dark), (esc(r["impressions"]), dark), (esc(r["position"]), gray)]
             for r in opportunities],
            gray=gray, border=border)
    brand = brand_rows(detail)
    if brand:
        html += _subtitle_html(BRAND_TITLE, BRAND_NOTE, esc=esc, dark=dark, gray=gray)
        head = ["", "Clics"] + ([change_head] if change_head else [])
        table_rows = []
        for row in brand:
            cells = [(esc(row["label"]), dark), (esc(row["clicks"]), dark)]
            if change_head:
                color = _GREEN if row["sign"] > 0 else _RED if row["sign"] < 0 else _NEUTRAL
                cells.append((esc(row["change"]), color))
            table_rows.append(cells)
        html += _detail_table_html(head, table_rows, gray=gray, border=border)
    return html


def render_html(seo: dict, *, esc, dark: str, gray: str, border: str) -> str:
    previous_month = _month_of(seo["previous"]).capitalize() if seo.get("previous") else None
    head_cells = f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">{_month_of(seo["month"]).capitalize()}</td>'
    if previous_month:
        head_cells += (
            f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">{esc(previous_month)}</td>'
            f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">Cambio</td>'
        )
    body = ""
    for row in rows(seo):
        color = _GREEN if row["sign"] > 0 else _RED if row["sign"] < 0 else _NEUTRAL
        cells = f'<td style="padding:8px 0;font-size:14px;color:{dark};text-align:right;font-weight:600;">{esc(row["current"])}</td>'
        if previous_month:
            cells += (
                f'<td style="padding:8px 0;font-size:14px;color:{gray};text-align:right;">{esc(row["previous"])}</td>'
                f'<td style="padding:8px 0;font-size:14px;color:{color};text-align:right;font-weight:600;">{esc(row["change"])}</td>'
            )
        body += (
            f'<tr><td style="padding:8px 0;font-size:14px;color:{dark};border-top:1px solid {border};">{esc(row["label"])}</td>'
            + cells.replace('<td style="padding:8px 0;', f'<td style="border-top:1px solid {border};padding:8px 0;')
            + "</tr>"
        )
    extra = year_ago_line(seo)
    extra_html = f'<p style="margin:10px 0 0 0;font-size:13px;color:{gray};">{esc(extra)}</p>' if extra else ""
    detail = detail_of(seo)
    if detail:
        extra_html += render_detail_html(detail, esc=esc, dark=dark, gray=gray, border=border)
    return f"""\
    <tr>
      <td style="padding:28px 0 0 0;">
        <p style="margin:0 0 6px 0;font-size:16px;font-weight:700;color:{dark};">{esc(title(seo))}</p>
        <p style="margin:0 0 12px 0;font-size:14px;color:{gray};line-height:1.5;">{esc(headline(seo))}</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr><td style="padding:6px 0;font-size:12px;color:{gray};"></td>{head_cells}</tr>
          {body}
        </table>
        {extra_html}
        <p style="margin:8px 0 0 0;font-size:12px;color:#999999;">Fuente: Google Search Console.</p>
      </td>
    </tr>"""
