"""Immutable additive schema step for scheduled job coordination and status."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration


_BYTES = (Path(__file__).with_name("schema_versions") / "job_runtime_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))


async def verify(conn):
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, is_nullable, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='job_runtime'
    """))).mappings().all()
    columns = {r["column_name"]: [r["udt_name"], r["is_nullable"] == "YES",
                                r["character_maximum_length"]] for r in rows}
    for name, expected in CONTRACT["columns"].items():
        if columns.get(name) != expected:
            raise RuntimeError(f"Unsupported schema: job_runtime.{name}")
    keys = (await conn.execute(text("""
        SELECT ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,p)
                     JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n
                     ORDER BY k.p) AS columns
        FROM pg_constraint c
        WHERE c.conrelid='public.job_runtime'::regclass AND c.contype='p'
    """))).scalars().all()
    if keys != [["key"]]:
        raise RuntimeError("Unsupported schema: job_runtime primary key")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
