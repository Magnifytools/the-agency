"""Varias cuentas de Google para Search Console.

La conexión deja de ser una fila única: cada cuenta es una fila con su id de
secuencia y su email (único), y cada propiedad recuerda con qué cuenta se
importa. El contrato publicado de gsc_v1 no cambia (sus columnas y su clave
primaria siguen igual), así que su verificación sigue pasando.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_indexes import check_unique_indexes
from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "gsc_accounts_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


async def verify(conn):
    singleton = await conn.scalar(text("""
        SELECT count(*) FROM pg_constraint
        WHERE conrelid='public.gsc_connection'::regclass AND conname='ck_gsc_connection_singleton'
    """))
    if singleton:
        raise RuntimeError("Unsupported schema: gsc_connection still allows a single account")
    default = await conn.scalar(text("""
        SELECT column_default FROM information_schema.columns
        WHERE table_schema='public' AND table_name='gsc_connection' AND column_name='id'
    """))
    if not default or "gsc_connection_id_seq" not in default:
        raise RuntimeError("Unsupported schema: gsc_connection.id has no sequence")
    for table, expected_columns in CONTRACT["columns"].items():
        rows = (await conn.execute(text("""
            SELECT column_name, udt_name, is_nullable, character_maximum_length
            FROM information_schema.columns WHERE table_schema='public' AND table_name=:table
        """), {"table": table})).mappings().all()
        columns = {r["column_name"]: [r["udt_name"], r["is_nullable"] == "YES",
                                    r["character_maximum_length"]] for r in rows}
        for name, expected in expected_columns.items():
            if columns.get(name) != expected:
                raise RuntimeError(f"Unsupported schema: {table}.{name}")
    fk = await conn.scalar(text("""
        SELECT c.confdeltype::text FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
        WHERE c.conrelid='public.gsc_site_sync'::regclass AND c.contype='f'
          AND c.confrelid='public.gsc_connection'::regclass AND a.attname='connection_id'
    """))
    if fk != "n":
        raise RuntimeError("Unsupported schema: gsc_site_sync.connection_id foreign key")
    await check_unique_indexes(conn, CONTRACT["unique_indexes"])


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
