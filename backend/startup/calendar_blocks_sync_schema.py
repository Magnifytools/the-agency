"""Paso aditivo: publicar los bloques de trabajo en Google Calendar (fase 4).

- ``user_blocks_calendars``: el calendario propio "The Agency" que la app creó
  en la cuenta de cada persona. Sin fila = no publica sus bloques. Tabla aparte
  y no columna de ``users``: los pasos de esquema anteriores insertan usuarios
  con el ORM.
- ``task_time_blocks.google_event_id`` / ``google_event_updated`` /
  ``google_synced_at``: el evento de cada bloque, su ``updated`` de Google en la
  última conciliación y cuándo se concilió (``services/calendar_blocks_sync.py``).

Tabla vacía y columnas nullable sin valor por defecto: nada cambia hasta que
alguien lo activa.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "calendar_blocks_sync_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


async def verify(conn):
    for table, expected_columns in CONTRACT["columns"].items():
        rows = (await conn.execute(text("""
            SELECT column_name, udt_name, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:table
        """), {"table": table})).mappings().all()
        columns = {r["column_name"]: [r["udt_name"], r["is_nullable"] == "YES",
                                    r["character_maximum_length"]] for r in rows}
        for name, expected in expected_columns.items():
            if columns.get(name) != expected:
                raise RuntimeError(f"Unsupported schema: {table}.{name}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
