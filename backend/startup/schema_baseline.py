"""Frozen P12 schema adoption/upgrade. No business seeds or historical rewrites.

SQL and structural contracts are immutable release artifacts, independent of
future ORM edits. Historical Alembic graphs are not replayed or stamped.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.startup.schema_indexes import check_unique_indexes
from backend.startup.schema_runner import Migration, run_schema_migrations


_ARTIFACT = Path(__file__).with_name("schema_versions") / "p12.json"
_BYTES = _ARTIFACT.read_bytes()
BASELINE = json.loads(_BYTES)
BASELINE_CHECKSUM = hashlib.sha256(_BYTES).hexdigest()
EXPECTED_SCHEMA_VERSION = "20260920_p12_schema"


async def _tables(conn):
    return set((await conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    ))).scalars())


async def check_structure(conn, *, allow_upgrade=False):
    tables = await _tables(conn)
    expected = BASELINE["columns"]
    optional_tables = set(BASELINE["optional_tables"]) if allow_upgrade else set()
    missing = set(expected) - tables - optional_tables
    if missing:
        raise RuntimeError(f"Unsupported schema: missing tables {', '.join(sorted(missing))}")
    rows = (await conn.execute(text("""
        SELECT c.table_name,c.column_name,c.udt_name,c.is_nullable,
               c.character_maximum_length,c.numeric_precision,c.numeric_scale
        FROM information_schema.columns c WHERE c.table_schema='public'
    """))).mappings().all()
    actual = {(r["table_name"], r["column_name"]): r for r in rows}
    for table, columns in expected.items():
        if table not in tables:
            continue
        optional = set(BASELINE["optional_columns"].get(table, [])) if allow_upgrade else set()
        for column, contract in columns.items():
            row = actual.get((table, column))
            if row is None and column in optional:
                continue
            if row is None:
                raise RuntimeError(f"Unsupported schema: missing column {table}.{column}")
            if row["udt_name"] not in contract["pg_types"]:
                raise RuntimeError(f"Unsupported schema: type of {table}.{column}")
            modifiers = contract.get("modifiers", {})
            if row["udt_name"] == "varchar" and row["character_maximum_length"] not in modifiers.get("varchar_lengths", []):
                raise RuntimeError(f"Unsupported schema: length of {table}.{column}")
            if row["udt_name"] == "numeric" and [row["numeric_precision"], row["numeric_scale"]] not in modifiers.get("numeric_shapes", []):
                raise RuntimeError(f"Unsupported schema: precision of {table}.{column}")
            # Nullable predecessors of explicitly upgraded columns are checked
            # after the step; other historical variants are named per column.
            if (row["is_nullable"] == "YES") not in contract["nullable_variants"]:
                raise RuntimeError(f"Unsupported schema: nullability of {table}.{column}")
    keys = (await conn.execute(text("""
        SELECT t.relname AS table_name,c.contype::text AS kind,
               c.confdeltype::text AS on_delete,c.convalidated,
               r.relname AS target_table,
               ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,p)
                     JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.n ORDER BY k.p) AS columns,
               ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n,p)
                     JOIN pg_attribute a ON a.attrelid=r.oid AND a.attnum=k.n ORDER BY k.p) AS target_columns
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        LEFT JOIN pg_class r ON r.oid=c.confrelid
        WHERE n.nspname='public' AND c.contype IN ('p','f')
    """))).mappings().all()
    for table, columns in expected.items():
        if table in tables:
            pk = [c for c, v in columns.items() if v["primary_key"]]
            if not any(k["table_name"] == table and k["kind"] == "p" and k["columns"] == pk for k in keys):
                raise RuntimeError(f"Unsupported schema: primary key of {table}")
    for fk in BASELINE["foreign_keys"]:
        if allow_upgrade and (fk["table"] not in tables or
                              any((fk["table"], c) not in actual for c in fk["columns"])):
            continue
        if not any(k["kind"] == "f" and k["convalidated"] and
                   k["table_name"] == fk["table"] and k["columns"] == fk["columns"] and
                   k["target_table"] == fk["target_table"] and k["target_columns"] == fk["target_columns"] and
                   k["on_delete"] == fk["on_delete"] for k in keys):
            raise RuntimeError(f"Unsupported schema: foreign key {fk['table']}.{','.join(fk['columns'])}")


async def preflight(conn):
    tables = await _tables(conn)
    if "alembic_version" in tables:
        # No released production shape has this table. Explicitly migrate a
        # reviewed historical revision before attempting adoption here.
        raise RuntimeError("Unsupported Alembic history; explicit adoption is required")
    business_tables = tables - {"agency_schema_versions"}
    if not business_tables:
        return
    await check_structure(conn, allow_upgrade=True)


async def _apply_enums(conn):
    for name, labels in BASELINE["enums"].items():
        values = ",".join("'" + label.replace("'", "''") + "'" for label in labels)
        # Names/values come only from the checked-in immutable release artifact.
        await conn.execute(text(f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                           WHERE n.nspname='public' AND t.typname='{name}') THEN
                CREATE TYPE public.{name} AS ENUM ({values});
            END IF;
        END $$"""))
        for label in labels:
            await conn.execute(text(f"ALTER TYPE public.{name} ADD VALUE IF NOT EXISTS '{label}'"))


async def _verify_enums(conn):
    rows = (await conn.execute(text("""
        SELECT t.typname,e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid
        JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'
    """))).all()
    found = {}
    for name, label in rows:
        found.setdefault(name, set()).add(label)
    for name, labels in BASELINE["enums"].items():
        if not set(labels) <= found.get(name, set()):
            raise RuntimeError(f"Required schema enum is incomplete: {name}")


async def _apply_schema(conn):
    tables = await _tables(conn)
    if not (tables - {"agency_schema_versions"}):
        for sql in BASELINE["bootstrap"]:
            await conn.execute(text(sql))
    else:
        # Adopt a fully verified existing release without even taking ALTER
        # locks or recreating equivalent legacy indexes under new names.
        try:
            async with conn.begin_nested():
                await _verify_schema(conn)
            return
        except (RuntimeError, DBAPIError):
            # Only an explicitly supported predecessor reaches this point:
            # preflight already rejected unknown columns/types/keys/history.
            pass
    for sql in BASELINE["upgrade"]:
        await conn.execute(text(sql))


async def _verify_schema(conn):
    await check_structure(conn)
    await check_unique_indexes(conn, BASELINE["unique_indexes"])


MIGRATIONS = (
    Migration("20260920_p12_enums", BASELINE_CHECKSUM, _apply_enums, _verify_enums),
    Migration(EXPECTED_SCHEMA_VERSION, BASELINE_CHECKSUM, _apply_schema, _verify_schema),
)


async def migrate_schema(engine):
    await run_schema_migrations(engine, MIGRATIONS, preflight)


async def check_schema_version(conn):
    rows = (await conn.execute(text(
        "SELECT version,checksum FROM agency_schema_versions ORDER BY version"
    ))).all()
    if list(rows) != sorted((m.version, m.checksum) for m in MIGRATIONS):
        raise RuntimeError("Required schema migration revision is not applied")


async def check_deployment_ready(engine):
    async with engine.connect() as conn:
        await check_schema_version(conn)
        await _verify_schema(conn)
        await _verify_enums(conn)
