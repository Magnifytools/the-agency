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
    render_email,
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


def _with_metrics() -> DigestContent:
    content = _content()
    content.sections.metrics = [
        DigestItem(title="Horas invertidas esta semana", description="Se han dedicado 13,2 horas al proyecto"),
        DigestItem(title="Tareas completadas esta semana", description="Se han cerrado 21 tareas"),
    ]
    return content


FIT_TEMPLATE = {
    "item_format": "simple",
    "sections": [
        {"key": "done", "title": "✅ Qué ha avanzado esta semana"},
        {"key": "metrics", "title": "📊 Métrica clave"},
        {"key": "need", "title": "🚨 Bloqueos o alertas"},
        {"key": "next", "title": "🎯 Foco de la semana que viene"},
    ],
}


def test_internal_metrics_never_reach_the_client_in_any_format():
    """Horas y tareas cerradas son internas (David, oct 2026): ni Slack, ni la
    plantilla de Fit que las pedía, ni email, ni texto plano."""
    content = _with_metrics()
    outputs = {
        "slack": render_slack(content),
        "slack_fit": render_slack(content, slack_template=FIT_TEMPLATE),
        "email": render_email(content),
        "email_plain": render_email_plain(content),
    }
    for name, out in outputs.items():
        assert "13,2 horas" not in out and "21 tareas" not in out, name
        assert "Métrica" not in out, name
        assert "Landing publicada" in out, name
    assert "✅ Qué ha avanzado esta semana" in outputs["slack_fit"]
    assert "🎯 Foco de la semana que viene" in outputs["slack_fit"]
