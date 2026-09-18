"""Additive schema only: no seeds, backfills, sends, or business-data cleanup."""
from sqlalchemy import text
from backend.db.models import CommunicationRequest, CommunicationSchedule, CommunicationOccurrence, Delivery, DeliveryAttempt


async def ensure_delivery_schema(engine):
    async with engine.begin() as conn:
        # Serializes this migration across concurrent web starts.
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241309)"))
        await conn.run_sync(lambda sync: CommunicationRequest.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: Delivery.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: DeliveryAttempt.__table__.create(sync, checkfirst=True))

        await conn.run_sync(lambda sync: CommunicationSchedule.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: CommunicationOccurrence.__table__.create(sync, checkfirst=True))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_calendar_synced_at TIMESTAMP"))
        await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS source_calendar_id VARCHAR(200)"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_events_google_scope ON events (user_id, source_calendar_id, google_event_id)"))
        # Replace only the legacy one-column unique constraint; preserve Event IDs.
        await conn.execute(text("""
            DO $$ DECLARE item RECORD; BEGIN
                FOR item IN SELECT c.conname FROM pg_constraint c
                  WHERE c.conrelid='events'::regclass AND c.contype='u'
                    AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='events'::regclass AND attname='google_event_id')]::smallint[]
                LOOP EXECUTE format('ALTER TABLE events DROP CONSTRAINT %I', item.conname); END LOOP;
            END $$;
        """))
