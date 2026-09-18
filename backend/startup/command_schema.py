from sqlalchemy import text


async def ensure_command_schema(engine) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS command_receipts (
        id VARCHAR(36) PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        request_key VARCHAR(64) NOT NULL, request_hash VARCHAR(64) NOT NULL,
        channel VARCHAR(12) NOT NULL, context JSONB, raw_text TEXT NOT NULL,
        status VARCHAR(20) NOT NULL, intent JSONB, prompt JSONB, result JSONB,
        change_log_id INTEGER REFERENCES change_logs(id) ON DELETE SET NULL,
        error_code VARCHAR(50), error_detail TEXT, revision INTEGER NOT NULL DEFAULT 1,
        step_replays JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(), updated_at TIMESTAMP NOT NULL DEFAULT NOW())""",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_command_receipts_user_key ON command_receipts(user_id, request_key)",
        "CREATE INDEX IF NOT EXISTS ix_command_receipts_user_created ON command_receipts(user_id, created_at DESC)",
    )
    async with engine.begin() as conn:
        # IF NOT EXISTS alone does not serialize concurrent first deployments.
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241313)"))
        for statement in statements:
            await conn.execute(text(statement))
