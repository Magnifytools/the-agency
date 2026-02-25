"""Digest Renderer: converts digest content into Slack or HTML email format.

Two output modes:
- Slack: emoji-based plain text with bullets, ready to paste into Slack.
- Email: HTML email with inline CSS, table-based layout, Magnify branding.
"""
from __future__ import annotations

from backend.schemas.digest import DigestContent, DigestItem


# ---------------------------------------------------------------------------
# Slack renderer
# ---------------------------------------------------------------------------

def render_discord(content: DigestContent) -> str:
    """Render digest content as Discord-formatted Markdown message."""
    lines: list[str] = []

    # Header
    date_str = content.date or "—"
    lines.append(f"**📊 Resumen diario — Magnify — {date_str}**")
    lines.append("")

    # Done section
    if content.sections.done:
        lines.append("**🎯 ¿Qué hemos hecho?**")
        for item in content.sections.done:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Need section
    if content.sections.need:
        lines.append("**⚠️ ¿Qué necesitamos?**")
        for item in content.sections.need:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Next section
    if content.sections.next:
        lines.append("**📋 ¿Qué vamos a hacer?**")
        for item in content.sections.next:
            desc = f" — {item.description}" if item.description else ""
            lines.append(f"• {item.title}{desc}")
        lines.append("")

    # Closing / AI note
    if content.closing:
        lines.append("**💡 Nota del día**")
        lines.append(content.closing)

    return "\n".join(lines)


def render_slack(content: DigestContent) -> str:
    """Render digest content as Slack-formatted text with emojis."""
    lines: list[str] = []

    # Greeting
    if content.greeting:
        lines.append(content.greeting)
    if content.date:
        lines.append(f"*{content.date}*")
    lines.append("")

    sections = content.sections

    # Done section
    if sections.done:
        lines.append(":white_check_mark:  *¿Qué hemos hecho?*")
        lines.append("")
        for item in sections.done:
            lines.append(f"  • *{item.title}*")
            if item.description:
                lines.append(f"    {item.description}")
        lines.append("")

    # Need section
    if sections.need:
        lines.append(":mega:  *¿Qué necesitamos?*")
        lines.append("")
        for item in sections.need:
            lines.append(f"  • *{item.title}*")
            if item.description:
                lines.append(f"    {item.description}")
        lines.append("")

    # Next section
    if sections.next:
        lines.append(":rocket:  *¿Qué vamos a hacer?*")
        lines.append("")
        for item in sections.next:
            lines.append(f"  • *{item.title}*")
            if item.description:
                lines.append(f"    {item.description}")
        lines.append("")

    # Closing
    if content.closing:
        lines.append("---")
        lines.append(content.closing)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email renderer — Magnify branded HTML
# ---------------------------------------------------------------------------

# Cloudinary icon URLs from the Magnify email template
ICON_DONE = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1739970609/pulsaG2_cfu8x2.png"
ICON_NEED = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1739970610/confirmarG_d6visb.png"
ICON_NEXT = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1739970396/hechoG2_msqumr.png"
LOGO_URL = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1748505370/logo-mail_cvckaw.webp"
LINKEDIN_ICON = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1739159379/linkedin-logo_rrf6tz.png"
X_ICON = "https://res.cloudinary.com/dk2qk66bj/image/upload/v1739159301/x-logo_efxegw.png"


def _render_item_row(item: DigestItem, icon_url: str) -> str:
    """Render a single item row with icon, title and description."""
    return f"""\
<tr style="border:none!important;">
  <td style="padding:9px;border:none!important;">
    <table role="presentation" style="width:100%;border-collapse:collapse;border:none!important;">
      <tr style="border:none!important;">
        <td style="width:50px;vertical-align:top;border:none!important;">
          <img src="{icon_url}" alt="" style="display:block;width:24px;height:24px;max-width:28px;max-height:28px;object-fit:contain;">
        </td>
        <td style="vertical-align:top;padding-left:12px;border:none!important;">
          <h3 style="margin:0 0 6px 0;font-size:16px;color:#333333;line-height:18px;font-weight:600;">{_esc(item.title)}</h3>
          <p style="margin:0;font-size:14px;color:#333333;line-height:16px;opacity:0.85;">{_esc(item.description)}</p>
        </td>
      </tr>
    </table>
  </td>
</tr>"""


def _render_section(title: str, items: list[DigestItem], icon_url: str) -> str:
    """Render a full section (header + divider + items)."""
    if not items:
        return ""

    items_html = "\n".join(_render_item_row(item, icon_url) for item in items)

    return f"""\
<tbody>
  <tr>
    <td colspan="2" style="padding:20px 15px 10px 15px;">
      <h2 style="font-size:18px;line-height:20px;margin:0!important;color:#1C1C1C;font-weight:700;">{_esc(title)}</h2>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding:10px 0;font-size:0;">
      <table border="0" width="100%" height="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:collapse;border-spacing:0px;">
        <tr><td style="border-bottom:2px solid #cccccc;height:1px;"></td></tr>
      </table>
    </td>
  </tr>
  {items_html}
</tbody>"""


def _esc(text: str) -> str:
    """Escape HTML entities."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_email(content: DigestContent) -> str:
    """Render digest content as Magnify-branded HTML email."""

    greeting_text = _esc(content.greeting) if content.greeting else ""
    date_text = _esc(content.date) if content.date else ""
    closing_text = _esc(content.closing) if content.closing else ""

    # Build dynamic sections
    sections_html = ""
    sections_html += _render_section(
        "¿Qué hemos hecho?", content.sections.done, ICON_DONE
    )
    sections_html += _render_section(
        "¿Qué necesitamos?", content.sections.need, ICON_NEED
    )
    sections_html += _render_section(
        "¿Qué vamos a hacer?", content.sections.next, ICON_NEXT
    )

    return f"""\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta content="telephone=no" name="format-detection">
  <title>Resumen Semanal — Magnify</title>
  <link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body style="font-family:'Lato',sans-serif;margin:0;padding:0;width:100%;background-color:#1C1C1C;">

<!-- WRAPPER -->
<div style="background-color:#1C1C1C;padding:15px 0;">
<table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-spacing:0px;">
<tr><td valign="top" style="padding:0;margin:0;">

<!-- HEADER -->
<table align="center" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;background-color:#E0E0E0;border-radius:20px 20px 0 0;width:100%;max-width:600px;" role="none">
  <tr>
    <td align="left" style="padding:20px;margin:0;">
      <table cellpadding="0" cellspacing="0" width="100%" role="presentation" style="border-collapse:collapse;border-spacing:0px;">
        <tr><td align="center" height="8" style="padding:0;margin:0;"></td></tr>
      </table>
    </td>
  </tr>
  <tr>
    <td align="left" style="padding:0 20px 10px 20px;margin:0;border-bottom:2px solid #0044FF;">
      <span style="margin:0;letter-spacing:0;font-size:16px;line-height:22px;color:#141212;">
        {greeting_text}<br/>
        Te enviamos el <strong>informe semanal: {date_text}</strong>
      </span>
    </td>
  </tr>
</table>

<!-- CONTENT BODY -->
<table align="center" cellpadding="0" cellspacing="0" style="width:600px;min-width:600px;background-color:#FFFFFF;padding-bottom:20px;" role="none">
  <tr>
    <td align="left" style="padding:0px 25px;">
      <table cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;border-spacing:0px;">
        {sections_html}
      </table>
    </td>
  </tr>
  <!-- Closing message -->
  <tr>
    <td align="left" style="padding:20px 25px 10px 25px;">
      <p style="margin:0;font-size:14px;color:#333333;line-height:20px;">{closing_text}</p>
    </td>
  </tr>
</table>

<!-- FOOTER -->
<table align="center" cellpadding="0" cellspacing="0" style="margin-top:-2px;width:600px;background-color:#E0E0E0;border-radius:0 0 20px 20px;" role="none">
  <tr>
    <td align="center" style="margin:0;padding-top:30px;padding-bottom:10px;">
      <table cellpadding="0" cellspacing="0" width="100%" role="none" style="border-collapse:collapse;border-spacing:0px;">
        <tr>
          <td align="center" style="width:600px;">
            <table cellpadding="0" cellspacing="0" width="100%" role="presentation" style="border-collapse:collapse;">
              <tr>
                <td align="center" style="padding:0;">
                  <table role="presentation" align="center" cellpadding="0" cellspacing="0" style="width:500px;border-collapse:collapse;">
                    <tr>
                      <td align="center" width="30%" style="padding:0 15px;">
                        <a href="https://www.magnify.ing" target="_blank" style="color:#1C1C1C;font-size:14px;line-height:12px;font-weight:bold;text-decoration:none;">Nosotros</a>
                      </td>
                      <td align="center" width="30%" style="padding:0 15px;">
                        <a href="https://www.magnify.ing" target="_blank" style="color:#1C1C1C;font-size:14px;line-height:12px;font-weight:bold;text-decoration:none;">Noticias</a>
                      </td>
                      <td align="center" width="30%" style="padding:0 15px;">
                        <a href="https://www.magnify.ing" target="_blank" style="color:#1C1C1C;font-size:14px;line-height:12px;font-weight:bold;text-decoration:none;">Nuestra web</a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
              <!-- Social icons -->
              <tr>
                <td align="center" style="padding:20px 0;">
                  <table role="presentation" align="center" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                    <tr>
                      <td align="center" style="padding:0 10px;">
                        <a href="https://www.magnify.ing" target="_blank">
                          <img src="{LINKEDIN_ICON}" width="15" height="15" alt="LinkedIn" style="display:block;">
                        </a>
                      </td>
                      <td align="center" style="padding:0 10px;">
                        <a href="https://www.magnify.ing" target="_blank">
                          <img src="{X_ICON}" width="15" height="15" alt="X" style="display:block;">
                        </a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding:20px 0 35px 0;text-align:center;width:100%;">
      <a href="https://www.magnify.ing" target="_blank" style="display:block;text-align:center;width:100%;">
        <img src="{LOGO_URL}" alt="Magnify" width="80" style="display:block;margin:0 auto;">
      </a>
    </td>
  </tr>
</table>

</td></tr>
</table>
</div>
</body>
</html>"""
