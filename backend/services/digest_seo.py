"""Bloque de Search Console de los resúmenes mensuales.

Se calcula y se pinta con código, no lo redacta la IA: el cliente ve
exactamente las cifras guardadas en `gsc_daily`. El bloque sólo existe cuando
`raw_context["seo"]["status"] == "ok"` y el contenido no lo ha desactivado.
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
    changes = seo.get("vs_year_ago") or {}
    if not seo.get("year_ago") or changes.get("clicks_pct") is None:
        return None
    month = format_month(date.fromisoformat(seo["year_ago"]["start"]))
    pct = changes["clicks_pct"]
    return f"Respecto a {month}: clics {'+' if pct > 0 else ''}{_dec(pct)} %."


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
    lines.append("Fuente: Google Search Console.")
    return lines


_GREEN, _RED, _NEUTRAL = "#15803D", "#B91C1C", "#666666"


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
