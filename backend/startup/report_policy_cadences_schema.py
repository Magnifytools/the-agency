"""Informe mensual y seguimiento semanal a la vez: un interruptor por cadencia.

Aditivo. Cada política activa pasa a tener encendida sólo la cadencia que ya
tenía; las desactivadas quedan con las dos apagadas. ``enabled``/``cadence``
siguen (las exige P12) hasta que un paso las retire.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "report_policy_cadences_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


async def verify(conn):
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='client_report_policies'
    """))).mappings().all()
    columns = {row["column_name"]: row for row in rows}
    for name, expected in CONTRACT["columns"].items():
        row = columns.get(name)
        actual = None if row is None else [
            row["udt_name"], row["is_nullable"] == "YES", row["column_default"],
        ]
        if actual != expected:
            raise RuntimeError(f"Unsupported schema: client_report_policies.{name}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
