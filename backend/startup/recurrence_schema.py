"""Add recurrence controls without rewriting historical calendars or tasks."""
from sqlalchemy import text


async def ensure_recurrence_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241316)"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_anchor_date DATE"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_paused_at TIMESTAMP WITHOUT TIME ZONE"))
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_occurrence_date DATE"))
        # An ambiguous historical duplicate blocks the upgrade transaction.
        # Never choose a task to discard or silently change its scheduled date.
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_task_recurring_occurrence
            ON tasks (recurring_parent_id, recurrence_occurrence_date)
            WHERE recurring_parent_id IS NOT NULL
        """))
        # Keep the generation receipt when a user deliberately deletes a child:
        # a periodic reconciliation must not resurrect that task.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_recurrence_occurrences (
                id SERIAL PRIMARY KEY,
                template_id INTEGER NOT NULL REFERENCES tasks(id),
                date DATE NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT timezone('UTC', now())
            )
        """))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_recurrence_consumed ON task_recurrence_occurrences(template_id,date)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_recurrence_generated ON task_recurrence_occurrences(task_id)"))
