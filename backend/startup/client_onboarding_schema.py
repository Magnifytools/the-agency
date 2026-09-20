"""Add terminal receipts for atomic client creation and recovery barriers."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "client_onboarding_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))


async def verify(conn):
    rows = (await conn.execute(text("""
        SELECT column_name,udt_name,is_nullable,character_maximum_length,column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='client_onboarding_receipts'
    """))).mappings().all()
    columns = {r["column_name"]: r for r in rows}
    for name, expected in CONTRACT["columns"].items():
        row = columns.get(name)
        if row is None or [row["udt_name"], row["is_nullable"] == "YES", row["character_maximum_length"]] != expected or row["column_default"] is not None:
            raise RuntimeError(f"Unsupported schema: client_onboarding_receipts.{name}")
    constraints = (await conn.execute(text("""
        SELECT c.conname,c.contype::text,c.convalidated,c.condeferrable,
               c.connoinherit,c.confdeltype::text,c.confupdtype::text,c.confmatchtype::text,
               pg_get_expr(c.conbin,c.conrelid) AS expression,
               ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,p)
                     JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n ORDER BY k.p) AS columns,
               n.nspname AS foreign_schema, t.relname AS foreign_table,
               ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n,p)
                     JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.p) AS foreign_columns
        FROM pg_constraint c
        LEFT JOIN pg_class t ON t.oid=c.confrelid
        LEFT JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE c.conrelid='public.client_onboarding_receipts'::regclass
    """))).mappings().all()
    primary = [r for r in constraints if r["contype"] == "p"]
    if len(primary) != 1 or primary[0]["columns"] != ["user_id", "request_key"] or primary[0]["condeferrable"]:
        raise RuntimeError("Unsupported schema: client_onboarding_receipts primary key")
    checks = {r["conname"]: r for r in constraints if r["contype"] == "c"}
    for name, expression in CONTRACT["checks"].items():
        row = checks.get(name)
        if row is None or not row["convalidated"] or row["connoinherit"] or row["expression"] != expression:
            raise RuntimeError(f"Unsupported schema: client_onboarding_receipts check {name}")
    foreign = [r for r in constraints if r["contype"] == "f"]
    for column, table, delete in [("user_id", "users", "c"), ("change_log_id", "change_logs", "n")]:
        matches = [r for r in foreign if r["columns"] == [column]]
        if len(matches) != 1 or not (
            matches[0]["foreign_schema"] == "public" and matches[0]["foreign_table"] == table
            and matches[0]["foreign_columns"] == ["id"] and matches[0]["confdeltype"] == delete
            and matches[0]["confupdtype"] == "a" and matches[0]["confmatchtype"] == "s"
            and matches[0]["convalidated"] and not matches[0]["condeferrable"]
        ):
            raise RuntimeError(f"Unsupported schema: client_onboarding_receipts foreign key {column}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
