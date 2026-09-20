"""Add condition state to notifications without activating historical activity."""
from sqlalchemy import text


async def ensure_incident_schema(engine):
    columns = {
        "incident_state": "VARCHAR(20)",
        "incident_severity": "VARCHAR(10)",
        "incident_revision": "INTEGER",
        "incident_detected_at": "TIMESTAMP WITHOUT TIME ZONE",
        "incident_fingerprint": "VARCHAR(64)",
        "incident_snoozed_until": "TIMESTAMP WITHOUT TIME ZONE",
        "incident_resolved_at": "TIMESTAMP WITHOUT TIME ZONE",
        "incident_resolution_reason": "VARCHAR(50)",
        "incident_dismissal_reason": "VARCHAR(500)",
        "entity_key": "VARCHAR(80)",
    }
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241314)"))
        for name, kind in columns.items():
            await conn.execute(text(f"ALTER TABLE notifications ADD COLUMN IF NOT EXISTS {name} {kind}"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_incident_state ON notifications (user_id, incident_state, id)"))
