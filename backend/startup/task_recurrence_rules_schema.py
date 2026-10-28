"""Recurrencia: varios días por semana y suelo de recuperación.

``recurrence_weekdays`` guarda los días (0-4) de la regla ``weekdays``.
``recurrence_since`` es desde cuándo el generador puede recuperar fechas que
no creó (alta, cambio de regla o reanudar). Ambas aditivas y NULL: las
plantillas existentes siguen igual y sin recuperación hacia atrás.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "task_recurrence_rules_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def verify(conn):
    for column, udt in CONTRACT["columns"].items():
        row = (await conn.execute(text("""
            SELECT udt_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='tasks' AND column_name=:column
        """), {"column": column})).mappings().one_or_none()
        if row is None or row["udt_name"] != udt or row["is_nullable"] != "YES" or row["column_default"] is not None:
            raise RuntimeError(f"Unsupported schema: tasks.{column}")


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
