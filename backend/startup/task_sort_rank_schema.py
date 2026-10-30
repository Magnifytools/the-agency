"""Orden manual de las tareas (arrastrar en Mi agenda y en el tablero).

Columna aditiva y nullable: NULL = sin orden manual, y esas tareas siguen
ordenándose como antes (vencidas, prioridad, fecha límite). El valor es un
índice fraccional (``services/task_rank.py``).
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "task_sort_rank_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def verify(conn):
    row = (await conn.execute(text("""
        SELECT udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='tasks'
          AND column_name=:column
    """), {"column": CONTRACT["column"]})).mappings().one_or_none()
    if row is None or (
        row["udt_name"] != CONTRACT["type"]
        or (row["is_nullable"] == "YES") != CONTRACT["nullable"]
        or row["column_default"] != CONTRACT["default"]
    ):
        raise RuntimeError("Unsupported schema: tasks.sort_rank")


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
