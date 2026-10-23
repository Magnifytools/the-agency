"""Paso aditivo de lo que The Agency hereda de The Engine (22 oct 2026):

- Leads por landing de GA4: `clients.ga4_lead_events` (qué eventos cuentan
  como lead), la tabla `ga4_lead_daily` y su estado en `ga4_property_sync`.
- Historial de posiciones importado de Engine: `gsc_query_monthly.source`
  ('google' | 'engine'); lo importado no caduca a los 16 meses.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "leads_engine_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


async def _columns(conn, table: str) -> dict:
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, is_nullable, character_maximum_length, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:table
    """), {"table": table})).mappings().all()
    return {r["column_name"]: r for r in rows}


async def verify(conn):
    clients = await _columns(conn, "clients")
    for name, expected in CONTRACT["client_columns"].items():
        row = clients.get(name)
        actual = None if row is None else [row["udt_name"], row["is_nullable"] == "YES", row["column_default"]]
        if actual != expected:
            raise RuntimeError(f"Unsupported schema: clients.{name}")
    for table, expected_columns in CONTRACT["tables"].items():
        columns = {name: [r["udt_name"], r["is_nullable"] == "YES", r["character_maximum_length"]]
                   for name, r in (await _columns(conn, table)).items()}
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
    for table, expected_checks in CONTRACT["checks"].items():
        checks = set((await conn.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid=CAST(:table AS regclass) AND contype='c'
        """), {"table": f"public.{table}"})).scalars().all())
        if not set(expected_checks) <= checks:
            raise RuntimeError(f"Unsupported schema: {table} checks")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
