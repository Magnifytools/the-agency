"""Paso aditivo para la integración con Vigil: slug en el cliente y su resumen."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_indexes import check_unique_indexes
from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "vigil_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)
# Lo que crea este paso lo borra ``vigil_retirement_v1``. Leído del contrato (no
# del módulo) para no importar en círculo; el checksum de ESTE paso no cambia.
RETIREMENT_VERSION = json.loads(
    (Path(__file__).with_name("schema_versions") / "vigil_retirement_v1.json").read_bytes()
)["version"]


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


async def verify(conn):
    # Ya retirado: que no esté es lo correcto (lo comprueba el paso de retirada).
    if await conn.scalar(text(
        "SELECT 1 FROM agency_schema_versions WHERE version=:version"
    ), {"version": RETIREMENT_VERSION}):
        return
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
    for table, expected_key in CONTRACT["primary_keys"].items():
        keys = (await conn.execute(text("""
            SELECT ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,p)
                         JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n
                         ORDER BY k.p) AS columns
            FROM pg_constraint c
            WHERE c.conrelid=CAST(:table AS regclass) AND c.contype='p'
        """), {"table": f"public.{table}"})).scalars().all()
        if keys != [expected_key]:
            raise RuntimeError(f"Unsupported schema: {table} primary key")
    await check_unique_indexes(conn, CONTRACT["unique_indexes"])


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
