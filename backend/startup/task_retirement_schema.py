"""Add reversible withdrawal metadata without changing task history."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "task_retirement_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def _verify_columns(conn):
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


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await _verify_columns(conn)
    exists = await conn.scalar(text("""
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.tasks'::regclass AND conname=:name
    """), {"name": CONTRACT["constraint_name"]})
    if not exists:
        await conn.execute(text(
            f"ALTER TABLE tasks ADD CONSTRAINT {CONTRACT['constraint_name']} "
            f"CHECK ({CONTRACT['constraint_expression']})"
        ))


async def verify(conn):
    await _verify_columns(conn)
    constraint = (await conn.execute(text("""
        SELECT contype::text, convalidated, connoinherit,
               pg_get_expr(conbin,conrelid) AS expression
        FROM pg_constraint
        WHERE conrelid='public.tasks'::regclass AND conname=:name
    """), {"name": CONTRACT["constraint_name"]})).mappings().one_or_none()
    if not constraint or not (
        constraint["contype"] == "c" and constraint["convalidated"]
        and not constraint["connoinherit"]
        and constraint["expression"] == CONTRACT["constraint_deparsed"]
    ):
        raise RuntimeError("Unsupported schema: tasks retirement constraint")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
