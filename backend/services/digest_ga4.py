"""Bloque de Google Analytics 4 de los resúmenes mensuales.

Como el de Search Console, lo calcula y lo pinta el código con las cifras de
``ga4_daily``: sesiones, conversiones (eventos clave) y lo que llega desde
asistentes de IA. Sólo existe si ``raw_context["ga4"]["status"] == "ok"`` y el
editor no lo ha quitado.
"""

from __future__ import annotations

from datetime import date

from backend.services.digest_periods import format_month
from backend.services.digest_seo import _GREEN, _NEUTRAL, _RED, _change, _dec, _int, _month_of


def is_available(ga4: dict | None) -> bool:
    return bool(ga4) and ga4.get("status") == "ok"


def _num(value: float | None) -> str:
    if value is None:
        return "—"
    return _int(int(value)) if float(value).is_integer() else _dec(value)


def title(ga4: dict) -> str:
    return f"Visitas y conversiones · {format_month(date.fromisoformat(ga4['month']['start']))}"


def headline(ga4: dict) -> str:
    month = ga4["month"]
    text = (f"En {_month_of(month)}, la web tuvo {_int(month['sessions'])} visitas y "
            f"{_num(month['key_events'])} conversiones")
    if month["ai_sessions"]:
        text += f"; {_int(month['ai_sessions'])} visitas llegaron desde asistentes de IA (ChatGPT, Perplexity, Gemini…)"
    return text + "."


def rows(ga4: dict) -> list[dict]:
    month, previous = ga4["month"], ga4.get("previous") or {}
    changes = ga4.get("vs_previous") or {}
    out = []
    for key, label in (("sessions", "Visitas"), ("key_events", "Conversiones"), ("ai_sessions", "Visitas desde IA")):
        change_text, sign = _change(changes.get(f"{key}_pct"), unit="%")
        out.append({"label": label, "current": _num(month.get(key)), "previous": _num(previous.get(key)),
                    "change": change_text, "sign": sign})
    return out


def render_text(ga4: dict, *, bold: str = "") -> list[str]:
    previous_month = _month_of(ga4["previous"]) if ga4.get("previous") else None
    lines = [f"{bold}{title(ga4)}{bold}", headline(ga4)]
    for row in rows(ga4):
        detail = row["current"]
        if previous_month:
            detail += f" (en {previous_month}: {row['previous']}; {row['change']})"
        lines.append(f"  - {row['label']}: {detail}")
    lines.append("Fuente: Google Analytics 4.")
    return lines


def render_html(ga4: dict, *, esc, dark: str, gray: str, border: str) -> str:
    previous_month = _month_of(ga4["previous"]).capitalize() if ga4.get("previous") else None
    head = f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">{_month_of(ga4["month"]).capitalize()}</td>'
    if previous_month:
        head += (f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">{esc(previous_month)}</td>'
                 f'<td style="padding:6px 0;font-size:12px;color:{gray};text-align:right;">Cambio</td>')
    body = ""
    for row in rows(ga4):
        color = _GREEN if row["sign"] > 0 else _RED if row["sign"] < 0 else _NEUTRAL
        cell = f'border-top:1px solid {border};padding:8px 0;font-size:14px;text-align:right;'
        cells = f'<td style="{cell}color:{dark};font-weight:600;">{esc(row["current"])}</td>'
        if previous_month:
            cells += (f'<td style="{cell}color:{gray};">{esc(row["previous"])}</td>'
                      f'<td style="{cell}color:{color};font-weight:600;">{esc(row["change"])}</td>')
        body += (f'<tr><td style="padding:8px 0;font-size:14px;color:{dark};border-top:1px solid {border};">'
                 f'{esc(row["label"])}</td>{cells}</tr>')
    return f"""\
    <tr>
      <td style="padding:28px 0 0 0;">
        <p style="margin:0 0 6px 0;font-size:16px;font-weight:700;color:{dark};">{esc(title(ga4))}</p>
        <p style="margin:0 0 12px 0;font-size:14px;color:{gray};line-height:1.5;">{esc(headline(ga4))}</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr><td style="padding:6px 0;font-size:12px;color:{gray};"></td>{head}</tr>
          {body}
        </table>
        <p style="margin:8px 0 0 0;font-size:12px;color:#999999;">Fuente: Google Analytics 4.</p>
      </td>
    </tr>"""
