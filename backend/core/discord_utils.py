"""Centralized Discord webhook/bot token resolution.

Reads from discord_settings DB table first, falls back to env var.
All other files should use these functions instead of inline decryption.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings

logger = logging.getLogger(__name__)


async def get_webhook_url(db: AsyncSession) -> str:
    """Get the decrypted Discord webhook URL. Returns empty string if not configured."""
    from backend.db.models import DiscordSettings
    from backend.core.security import decrypt_vault_secret

    try:
        result = await db.execute(select(DiscordSettings).limit(1))
        ds = result.scalar_one_or_none()
        if ds and ds.webhook_url:
            raw = ds.webhook_url
            if raw.startswith("v1:"):
                return decrypt_vault_secret(raw)
            return raw
    except Exception as e:
        logger.warning("Failed to read Discord webhook from DB: %s", e)

    return settings.DISCORD_WEBHOOK_URL or ""


async def get_bot_token(db: AsyncSession) -> Optional[str]:
    """Get the decrypted Discord bot token. Returns None if not configured."""
    from backend.db.models import DiscordSettings
    from backend.core.security import decrypt_vault_secret

    try:
        result = await db.execute(select(DiscordSettings).limit(1))
        ds = result.scalar_one_or_none()
        if ds and ds.bot_token:
            raw = ds.bot_token
            if raw.startswith("v1:"):
                return decrypt_vault_secret(raw)
            return raw
    except Exception as e:
        logger.warning("Failed to read Discord bot token from DB: %s", e)

    return None
