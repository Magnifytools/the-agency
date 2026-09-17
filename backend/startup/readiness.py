"""Read-only deployment readiness: database connectivity and required schema."""
import asyncio

from sqlalchemy import text


async def check_database_ready(engine) -> None:
    async def probe():
        async with engine.connect() as conn:
            # LIMIT 0 verifies the actual schema without reading business data.
            await conn.execute(text("SELECT completed_at FROM tasks LIMIT 0"))
            await conn.execute(text("SELECT dedupe_key FROM notifications LIMIT 0"))
            await conn.execute(text("SELECT paused_at, accumulated_seconds FROM time_entries LIMIT 0"))
            # Production's legacy timer index has a different name. Validate
            # semantics, so an equivalent index passes and a wrongly named one
            # with different keys cannot falsely certify the schema.
            for table, columns, predicate in (
                ("notifications", ["user_id", "dedupe_key"], ""),
                ("time_entries", ["user_id"], "(minutes IS NULL)"),
            ):
                valid = await conn.scalar(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_index i
                        WHERE i.indrelid = to_regclass(:table)
                          AND i.indisvalid AND i.indisunique
                          AND i.indnkeyatts = cardinality(CAST(:columns AS text[]))
                          AND ARRAY(
                            SELECT a.attname::text
                            FROM unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum, position)
                            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
                            WHERE k.position <= i.indnkeyatts ORDER BY k.position
                          ) = CAST(:columns AS text[])
                          AND coalesce(pg_get_expr(i.indpred, i.indrelid), '') = :predicate
                    )
                """), {"table": table, "columns": columns, "predicate": predicate})
                if valid is not True:
                    raise RuntimeError("Required unique index is missing or invalid")
    await asyncio.wait_for(probe(), timeout=5)
