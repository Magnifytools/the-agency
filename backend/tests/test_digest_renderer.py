"""Unit tests for the digest renderer — focus on the closing ("cierre") never
being dropped across channels, including custom per-client Slack templates.

Regression: Fit Generation's custom Slack template dropped the closing because
the renderer honored a `show_closing` opt-out. The closing is the client-facing
sign-off and must always render when present, like every other channel.
"""
from __future__ import annotations

from backend.schemas.digest import DigestContent, DigestSections, DigestItem
from backend.services.digest_renderer import (
    render_slack,
    render_discord,
    render_email_plain,
)


def _content() -> DigestContent:
    return DigestContent(
        greeting="Hola Fit Generation 👋",
        date="Semana del 16 al 22 de junio 2026",
        sections=DigestSections(
            done=[DigestItem(title="Landing publicada", description="Nueva home live")],
            need=[],
            next=[DigestItem(title="Campaña ads", description="Arrancamos lunes")],
        ),
        closing="¡Gracias por la semana! Cualquier duda nos dices 🙌",
    )


def test_slack_default_includes_closing():
    out = render_slack(_content())
    assert "¡Gracias por la semana!" in out


def test_slack_custom_includes_closing_even_when_template_disables_it():
    # Template explicitly sets show_closing=False (the old Fit Generation case).
    template = {
        "header": "📊 Resumen — Semana {week}",
        "item_format": "simple",
        "show_greeting": False,
        "show_date": False,
        "show_closing": False,  # must be ignored now
        "sections": [
            {"key": "done", "title": "✅ Hecho"},
            {"key": "need", "title": "🚧 Bloqueos", "empty_text": "Sin bloqueos"},
            {"key": "next", "title": "📋 Próximo"},
        ],
    }
    out = render_slack(_content(), slack_template=template)
    assert "¡Gracias por la semana!" in out
    assert "Sin bloqueos" in out  # empty_text still works


def test_slack_custom_no_closing_when_content_empty():
    template = {"sections": [{"key": "done", "title": "Hecho"}]}
    content = _content()
    content.closing = ""
    out = render_slack(content, slack_template=template)
    assert "---" not in out  # no separator when there's no closing


def test_discord_and_email_plain_include_closing():
    c = _content()
    assert "¡Gracias por la semana!" in render_discord(c)
    assert "¡Gracias por la semana!" in render_email_plain(c)
