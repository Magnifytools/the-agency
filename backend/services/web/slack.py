"""Envío a Slack por incoming webhook (portado de Vigil, en async).

Un fallo aquí NUNCA tumba el ciclo: la caída ya está guardada y visible en la
app y en la bandeja de alertas. Slack es sólo el canal de aviso y los avisos
van por outbox (``web_outages.slack_*_status``): si falla, se reintenta en el
siguiente ciclo, así que aquí no hay reintentos ni esperas. ``post_message`` no
lanza: devuelve un resultado que el llamante anota.

Sólo se aceptan webhooks de ``https://hooks.slack.com/services/…``: el webhook
lo teclea un admin y se pide desde nuestro servidor, así que tampoco puede
apuntar a ningún otro sitio.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status: int | None = None
    error: str | None = None
    # True si el webhook ya no sirve (revocado/borrado en Slack) y hace falta
    # que alguien genere otro. Distinto de un fallo transitorio.
    revoked: bool = False


def is_valid_webhook(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url.startswith(_WEBHOOK_PREFIX) or len(url) > 300:
        return False
    rest = url[len(_WEBHOOK_PREFIX):]
    parts = rest.split("/")
    return len(parts) == 3 and all(p and p.replace("_", "").replace("-", "").isalnum() for p in parts)


def normalize_channel(channel: str | None) -> str | None:
    """``seo-equipo`` → ``#seo-equipo``. Sólo se enseña: el webhook manda."""
    if not channel or not channel.strip():
        return None
    channel = channel.strip()
    return channel if channel.startswith(("#", "@")) else f"#{channel}"


async def post_message(
    webhook_url: str, text: str, blocks: list[dict] | None = None,
    *, transport: httpx.AsyncBaseTransport | None = None,
) -> DeliveryResult:
    """Publica un mensaje. ``text`` es lo que sale en la notificación del móvil."""
    if not is_valid_webhook(webhook_url):
        return DeliveryResult(ok=False, error="El webhook no es de Slack.")
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport, follow_redirects=False) as client:
            response = await client.post(webhook_url, json=payload)
    except httpx.HTTPError as exc:
        return DeliveryResult(ok=False, error=f"red: {type(exc).__name__}")
    if response.status_code == 200:
        return DeliveryResult(ok=True, status=200)
    # 404/410: el webhook se borró o se revocó en Slack (o el canal se archivó).
    # Reintentar no lo arregla; hace falta que alguien genere uno nuevo.
    if response.status_code in (404, 410):
        return DeliveryResult(
            ok=False, status=response.status_code, revoked=True,
            error="El webhook ya no existe en Slack. Genera uno nuevo.",
        )
    if response.status_code == 403 and "invalid_token" in response.text:
        return DeliveryResult(ok=False, status=403, revoked=True,
                              error="Slack ya no acepta este webhook. Genera uno nuevo.")
    logger.warning("Slack respondió %s", response.status_code)
    return DeliveryResult(ok=False, status=response.status_code, error=response.text[:200])


async def send_test_message(
    webhook_url: str, client_name: str, *, transport: httpx.AsyncBaseTransport | None = None,
) -> DeliveryResult:
    text = f"The Agency: prueba de avisos de la web de {client_name}"
    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": (
            f"*{text}*\nSi ves este mensaje, el webhook está bien configurado. "
            "Aquí llegará un aviso si la web deja de responder y otro cuando vuelva."
        )},
    }]
    return await post_message(webhook_url, text, blocks, transport=transport)
