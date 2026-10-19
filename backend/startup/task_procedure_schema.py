"""Add the written procedure of recurring templates (and its copy on each occurrence)."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "task_procedure_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await verify(conn)


async def verify(conn):
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, is_nullable, character_maximum_length, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='tasks'
    """))).mappings().all()
    columns = {row["column_name"]: row for row in rows}
    for name, expected in CONTRACT["columns"].items():
        row = columns.get(name)
        actual = None if row is None else [
            row["udt_name"], row["is_nullable"] == "YES", row["character_maximum_length"],
        ]
        if actual != expected or row["column_default"] is not None:
            raise RuntimeError(f"Unsupported schema: tasks.{name}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
