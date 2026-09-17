"""Additive schema only: no seeds, backfills, sends, or business-data cleanup."""
from sqlalchemy import text
from backend.db.models import Delivery, DeliveryAttempt


async def ensure_delivery_schema(engine):
    async with engine.begin() as conn:
        # Serializes this migration across concurrent web starts.
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241309)"))
        await conn.run_sync(lambda sync: Delivery.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: DeliveryAttempt.__table__.create(sync, checkfirst=True))
