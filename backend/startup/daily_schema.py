"""Preserve daily drafts while adding revision and source evidence contracts."""
from sqlalchemy import text


async def ensure_daily_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241315)"))
        await conn.execute(text("ALTER TABLE daily_updates ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1"))
        await conn.execute(text("ALTER TABLE daily_updates ADD COLUMN IF NOT EXISTS source_facts JSON NOT NULL DEFAULT '[]'"))
        # Fail without modifying ambiguous historical rows. Deployments must
        # never choose which person's text to discard to satisfy an index.
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_user_date ON daily_updates (user_id, date)"))
