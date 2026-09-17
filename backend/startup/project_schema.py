"""Add explicit ownership without inferring owners for existing projects."""
from sqlalchemy import text


async def ensure_project_owner_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241310)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id INTEGER"))
        await conn.execute(text("""DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint c
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.conrelid = 'projects'::regclass AND c.contype = 'f'
                  AND c.confrelid = 'users'::regclass AND a.attname = 'owner_id'
            ) THEN
                ALTER TABLE projects ADD CONSTRAINT projects_owner_id_fkey
                    FOREIGN KEY (owner_id) REFERENCES users(id);
            END IF;
        END $$"""))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"))
