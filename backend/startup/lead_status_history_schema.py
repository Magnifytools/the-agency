"""Pipeline: historial de etapas de cada lead (el embudo lo necesita).

Tabla nueva; cada lead existente arranca con UNA fila: su etapa actual desde su
última modificación (no se sabe cuándo entró en las anteriores y no se inventa).
Desde ahí, crear un lead y cada cambio de etapa añaden la suya.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "lead_status_history_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def verify(conn):
    rows = dict((await conn.execute(text("""
        SELECT column_name, udt_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='lead_status_history'
    """))).all())
    if rows != CONTRACT["columns"]:
        raise RuntimeError("Unsupported schema: lead_status_history")


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
