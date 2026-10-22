"""Cliente en Engine (= Anvil) por cliente: sólo su uuid, para el botón
"Abrir en Engine". The Agency no lee ni guarda datos de Engine."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "client_content_engine_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await verify(conn)


async def verify(conn):
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, character_maximum_length, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='clients'
    """))).mappings().all()
    columns = {row["column_name"]: row for row in rows}
    for name, expected in CONTRACT["columns"].items():
        row = columns.get(name)
        actual = None if row is None else [
            row["udt_name"], row["character_maximum_length"],
            row["is_nullable"] == "YES", row["column_default"],
        ]
        if actual != expected:
            raise RuntimeError(f"Unsupported schema: clients.{name}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
