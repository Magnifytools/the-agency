"""Utilidades OAuth de Google compartidas por Search Console/GA4 y Calendar."""

from __future__ import annotations

import logging

import httpx

from backend.core.security import decrypt_vault_secret

logger = logging.getLogger(__name__)

REVOKE_URL = "https://oauth2.googleapis.com/revoke"
REVOKE_TIMEOUT_SECONDS = 10


def plain_refresh_token(stored: str | None) -> str | None:
    """Token en claro a partir de lo guardado (cifrado ``v1:`` o, en Calendar
    antiguo, en claro). ``None`` si no hay token o no se puede descifrar."""
    if not stored:
        return None
    if not stored.startswith("v1:"):
        return stored
    try:
        return decrypt_vault_secret(stored)
    except ValueError:
        logger.warning("No se pudo descifrar un token de Google para revocarlo")
        return None


async def revoke_token(refresh_token: str | None) -> bool:
    """Revoca el token en Google. ``True`` sólo si Google lo confirma (HTTP 200).

    Nunca lanza: quien desconecta borra su copia local igualmente (el token
    puede estar ya caducado o revocado desde la cuenta de Google). Revocar un
    refresh token retira a The Agency TODO el permiso que esa cuenta de Google
    le había dado (Google agrupa los permisos por cuenta y aplicación).
    """
    if not refresh_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=REVOKE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                REVOKE_URL,
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:  # noqa: BLE001 — revocar nunca debe tumbar la desconexión
        logger.warning("No se pudo revocar el token en Google (%s)", type(exc).__name__)
        return False
    if response.status_code != 200:
        # El cuerpo no se registra: no aporta y podría repetir datos del token.
        logger.warning("Google no confirmó la revocación del token (HTTP %s)", response.status_code)
        return False
    return True
