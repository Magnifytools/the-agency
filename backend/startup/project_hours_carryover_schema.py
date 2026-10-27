"""Opt-in por proyecto: las horas del mes que sobran o faltan pasan al siguiente.

Columna aditiva con DEFAULT false: los proyectos existentes se miden igual que
antes (cada mes empieza de cero).
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "project_hours_carryover_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def verify(conn):
    row = (await conn.execute(text("""
        SELECT udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='projects'
          AND column_name=:column
    """), {"column": CONTRACT["column"]})).mappings().one_or_none()
    if row is None or (
        row["udt_name"] != CONTRACT["type"]
        or (row["is_nullable"] == "YES") != CONTRACT["nullable"]
        or row["column_default"] != CONTRACT["default"]
    ):
        raise RuntimeError("Unsupported schema: projects.hours_carryover")


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
