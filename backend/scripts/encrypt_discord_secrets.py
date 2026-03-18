"""
One-time migration: encrypt any existing plaintext Discord webhook URLs and bot tokens.

Usage:
    python -m backend.scripts.encrypt_discord_secrets

Safe to run multiple times — skips already-encrypted (v1: prefixed) values.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate():
    from sqlalchemy import select, text
    from backend.db.database import engine
    from backend.core.security import encrypt_vault_secret

    async with engine.begin() as conn:
        # Check if table exists
        check = await conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_settings'")
        )
        if check.scalar() is None:
            logger.info("discord_settings table does not exist — nothing to migrate.")
            return

        rows = await conn.execute(text("SELECT id, webhook_url, bot_token FROM discord_settings"))
        updated = 0
        for row in rows.fetchall():
            row_id, webhook_url, bot_token = row
            changes: dict[str, str] = {}

            if webhook_url and not webhook_url.startswith("v1:"):
                changes["webhook_url"] = encrypt_vault_secret(webhook_url)

            if bot_token and not bot_token.startswith("v1:"):
                changes["bot_token"] = encrypt_vault_secret(bot_token)

            if changes:
                set_clauses = ", ".join(f"{k} = :{k}" for k in changes)
                changes["id"] = row_id
                await conn.execute(
                    text(f"UPDATE discord_settings SET {set_clauses} WHERE id = :id"),
                    changes,
                )
                updated += 1
                logger.info("Encrypted secrets for discord_settings id=%s (fields: %s)",
                            row_id, ", ".join(k for k in changes if k != "id"))

        if updated:
            logger.info("Migration complete: %d row(s) encrypted.", updated)
        else:
            logger.info("No plaintext secrets found — nothing to migrate.")


def main():
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
