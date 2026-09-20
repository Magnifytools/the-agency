"""Exercise the actual additive startup DDL against legacy-shaped tables."""
from backend.startup.schema_baseline import BASELINE

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_phase1_upgrade_is_idempotent_and_preserves_legacy_rows(engine):
    statements = [sql for sql in BASELINE["upgrade"] if sql.startswith((
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at",
        "CREATE INDEX IF NOT EXISTS ix_tasks_completed_at",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_dedupe",
    ))]
    assert len(statements) == 4
    async with engine.begin() as conn:
        # Temporary tables shadow public ones only on this connection.
        await conn.execute(text("CREATE TEMP TABLE tasks (id INTEGER PRIMARY KEY, title TEXT) ON COMMIT DROP"))
        await conn.execute(text("CREATE TEMP TABLE notifications (id SERIAL PRIMARY KEY, user_id INTEGER, title TEXT, is_read BOOLEAN) ON COMMIT DROP"))
        await conn.execute(text("INSERT INTO tasks VALUES (1, 'Legacy task')"))
        await conn.execute(text("INSERT INTO notifications(user_id,title,is_read) VALUES (1, 'Legacy read alert', true)"))
        for _ in range(2):
            for statement in statements:
                await conn.execute(text(statement))
        assert (await conn.execute(text("SELECT title,completed_at FROM tasks"))).one() == ("Legacy task", None)
        assert (await conn.execute(text("SELECT title,is_read,dedupe_key FROM notifications"))).one() == ("Legacy read alert", True, None)
        await conn.execute(text("INSERT INTO notifications(user_id,dedupe_key) VALUES (1,'cycle-a'),(2,'cycle-a')"))
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(text("INSERT INTO notifications(user_id,dedupe_key) VALUES (1,'cycle-a')"))
