"""Digest Renderer: converts digest content into Slack, Discord or HTML email format.

Three output modes:
- Slack: emoji-based plain text with bullets, ready to paste into Slack.
- Discord: Markdown-formatted text with emojis.
- Email: Minimal HTML email with Magnify branding.
"""
from __future__ import annotations

from datetime import date

from backend.db.models import DigestTone
from backend.schemas.digest import DigestContent, DigestItem


# ---------------------------------------------------------------------------
# Section titles by person (singular vs plural)
# ---------------------------------------------------------------------------

SECTION_TITLES_SINGULAR = {
    "done": "¿Qué he hecho?",
    "need": "¿Qué necesito?",
    "next": "¿Qué voy a hacer?",
    "metrics": "Métricas clave",
}

SECTION_TITLES_PLURAL = {
    "done": "¿Qué hemos hecho?",
    "need": "¿Qué necesitamos?",
    "next": "¿Qué vamos a hacer?",
    "metrics": "Métricas clave",
}


def _section_titles(tone: DigestTone | None = None) -> dict[str, str]:
    """Return section titles based on tone — singular for cercano/formal, plural for equipo."""
    if tone == DigestTone.equipo:
        return SECTION_TITLES_PLURAL
    return SECTION_TITLES_SINGULAR


# ---------------------------------------------------------------------------
# Discord renderer
# ---------------------------------------------------------------------------

def render_discord(content: DigestContent, tone: DigestTone | None = None) -> str:
    """Render digest content as Discord-formatted Markdown message."""
    titles = _section_titles(tone)
    lines: list[str] = []

    # Header
    date_str = content.date or "—"
    lines.append(f"**📊 Resumen diario — Magnify — {date_str}**")
    lines.append("")

    # Done section
    if content.sections.done:
        lines.append(f"**🎯 {titles['done']}**")
        for item in content.sections.done:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Need section
    if content.sections.need:
        lines.append(f"**⚠️ {titles['need']}**")
        for item in content.sections.need:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Next section
    if content.sections.next:
        lines.append(f"**📋 {titles['next']}**")
        for item in content.sections.next:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Closing / AI note
    if content.closing:
        lines.append("**💡 Nota del día**")
        lines.append(content.closing)

    return "\n".join(lines)


def render_slack(
    content: DigestContent,
    tone: DigestTone | None = None,
    slack_template: dict | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> str:
    """Render digest content as Slack mrkdwn text (paste-friendly).

    If slack_template is provided, uses the custom per-client format.
    Otherwise uses the default Magnify format.
    """
    if slack_template:
        return _render_slack_custom(content, slack_template, period_start, period_end)
    return _render_slack_default(content, tone)


def _render_slack_default(content: DigestContent, tone: DigestTone | None = None) -> str:
    """Default Slack format — Magnify standard."""
    titles = _section_titles(tone)
    lines: list[str] = []

    if content.greeting:
        lines.append(content.greeting)
    if content.date:
        lines.append(f"*{content.date}*")
    lines.append("")

    sections = content.sections

    for key in ("done", "need", "next", "metrics"):
        items = getattr(sections, key, [])
        if items:
            title = titles.get(key, key.capitalize())
            lines.append(f"*{title}*")
            for item in items:
                lines.append(f"- *{item.title}*")
                if item.description:
                    lines.append(f"  {item.description}")
            lines.append("")

    if content.closing:
        lines.append("---")
        lines.append(content.closing)

    return "\n".join(lines)


def _render_slack_custom(
    content: DigestContent,
    template: dict,
    period_start: date | None = None,
    period_end: date | None = None,
) -> str:
    """Custom per-client Slack format based on template config."""
    lines: list[str] = []
    sections_data = content.sections

    # Header
    header_tpl = template.get("header", "")
    if header_tpl:
        area = template.get("area", "")
        week_num = period_start.isocalendar()[1] if period_start else ""
        header = header_tpl.format(area=area, week=week_num, project=area)
        lines.append(header)
        lines.append("")

    # Greeting (optional)
    if template.get("show_greeting", False) and content.greeting:
        lines.append(content.greeting)
        lines.append("")

    # Sections in template order
    item_format = template.get("item_format", "simple")
    for sec in template.get("sections", []):
        key = sec.get("key", "")
        title = sec.get("title", "")
        empty_text = sec.get("empty_text")
        items = getattr(sections_data, key, [])

        if not items and not empty_text:
            continue

        if title:
            lines.append(title)

        if items:
            for item in items:
                if item_format == "simple":
                    text = item.title
                    if item.description:
                        text = f"{item.title}: {item.description}"
                    lines.append(f"- {text}")
                else:
                    lines.append(f"- *{item.title}*")
                    if item.description:
                        lines.append(f"  {item.description}")
        elif empty_text:
            lines.append(f"- {empty_text}")

        lines.append("")

    # Closing (optional)
    if template.get("show_closing", False) and content.closing:
        lines.append("---")
        lines.append(content.closing)

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Email renderer — Magnify minimal HTML
# ---------------------------------------------------------------------------

LOGO_URL = "https://magnify.ing/wp-content/uploads/2026/01/magnify-c.png"

# Brand color
_BLUE = "#0044FF"
_DARK = "#1A1A1A"
_GRAY = "#666666"
_LIGHT_BG = "#F7F7F7"
_BORDER = "#E5E5E5"

# Section accent dots
_SECTION_COLORS = {
    "done": "#22C55E",   # green
    "need": "#F59E0B",   # amber
    "next": "#3B82F6",   # blue
}


def _esc(text: str) -> str:
    """Escape HTML entities."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_period(period_start: date | None, period_end: date | None) -> str:
    """Format period dates in Spanish. Returns e.g. 'Semana del 31 de marzo al 4 de abril 2026'."""
    if not period_start or not period_end:
        return ""
    months = [
        "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    if period_start.month == period_end.month:
        return f"Semana del {period_start.day} al {period_end.day} de {months[period_end.month]} {period_end.year}"
    return f"Semana del {period_start.day} de {months[period_start.month]} al {period_end.day} de {months[period_end.month]} {period_end.year}"


def _render_item_email(item: DigestItem) -> str:
    """Render a single item as a clean row."""
    return f"""\
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid {_BORDER};">
          <p style="margin:0 0 4px 0;font-size:15px;color:{_DARK};font-weight:600;line-height:1.4;">{_esc(item.title)}</p>
          <p style="margin:0;font-size:14px;color:{_GRAY};line-height:1.5;">{_esc(item.description)}</p>
        </td>
      </tr>"""


def _render_section_email(title: str, items: list[DigestItem], color: str) -> str:
    """Render a full section with colored accent."""
    if not items:
        return ""

    items_html = "\n".join(_render_item_email(item) for item in items)

    return f"""\
    <tr>
      <td style="padding:28px 0 0 0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
          <tr>
            <td style="padding-bottom:12px;">
              <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:10px;vertical-align:middle;"></span>
              <span style="font-size:16px;font-weight:700;color:{_DARK};vertical-align:middle;">{_esc(title)}</span>
            </td>
          </tr>
          {items_html}
        </table>
      </td>
    </tr>"""


def render_email(
    content: DigestContent,
    tone: DigestTone | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    logo_url: str | None = None,
) -> str:
    """Render digest content as a clean, minimal HTML email."""
    titles = _section_titles(tone)

    greeting_text = _esc(content.greeting).replace("\n", "<br>") if content.greeting else ""
    # Use real dates from the digest period, falling back to AI-generated text
    date_text = _format_period(period_start, period_end) or _esc(content.date) if content.date else _format_period(period_start, period_end)
    # Closing supports HTML (for links like Google Sheets trackers)
    closing_text = content.closing.replace("\n", "<br>") if content.closing else ""
    logo = logo_url or LOGO_URL

    # Build sections
    sections_html = ""
    sections_html += _render_section_email(titles["done"], content.sections.done, _SECTION_COLORS["done"])
    sections_html += _render_section_email(titles["need"], content.sections.need, _SECTION_COLORS["need"])
    sections_html += _render_section_email(titles["next"], content.sections.next, _SECTION_COLORS["next"])

    return f"""\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Resumen Semanal — Magnify</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background-color:{_LIGHT_BG};font-family:'Inter','Helvetica Neue',Arial,sans-serif;-webkit-font-smoothing:antialiased;">

<table width="100%" cellpadding="0" cellspacing="0" style="background-color:{_LIGHT_BG};padding:32px 16px;">
<tr><td align="center">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background-color:#FFFFFF;border-radius:12px;overflow:hidden;">

  <!-- Header -->
  <tr>
    <td style="padding:32px 32px 24px 32px;border-bottom:3px solid {_BLUE};">
      <p style="margin:0 0 12px 0;font-size:15px;color:{_DARK};line-height:1.5;">{greeting_text}</p>
      <p style="margin:0;font-size:13px;color:{_GRAY};font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{date_text}</p>
    </td>
  </tr>

  <!-- Content -->
  <tr>
    <td style="padding:0 32px 24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        {sections_html}
      </table>
    </td>
  </tr>

  <!-- Closing -->
  <tr>
    <td style="padding:16px 32px 32px 32px;">
      <p style="margin:0;font-size:14px;color:{_DARK};line-height:1.6;">{closing_text}</p>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="padding:20px 32px;background-color:{_LIGHT_BG};text-align:center;">
      <a href="https://www.magnify.ing" target="_blank" style="text-decoration:none;">
        <img src="{logo}" alt="Magnify" width="64" style="display:inline-block;">
      </a>
      <p style="margin:10px 0 0 0;font-size:12px;color:#999999;">
        <a href="https://www.magnify.ing" target="_blank" style="color:#999999;text-decoration:none;">magnify.ing</a>
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>"""


def render_email_plain(content: DigestContent, tone: DigestTone | None = None) -> str:
    """Render digest content as plain text for email (no HTML)."""
    titles = _section_titles(tone)
    lines: list[str] = []

    if content.greeting:
        lines.append(content.greeting)
    if content.date:
        lines.append(content.date)
    lines.append("")

    if content.sections.done:
        lines.append(f"--- {titles['done']} ---")
        for item in content.sections.done:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"  - {item.title}{desc}")
        lines.append("")

    if content.sections.need:
        lines.append(f"--- {titles['need']} ---")
        for item in content.sections.need:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"  - {item.title}{desc}")
        lines.append("")

    if content.sections.next:
        lines.append(f"--- {titles['next']} ---")
        for item in content.sections.next:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"  - {item.title}{desc}")
        lines.append("")

    if content.closing:
        lines.append(content.closing)
        lines.append("")

    lines.append("—")
    lines.append("Magnify · magnify.ing")

    return "\n".join(lines)
