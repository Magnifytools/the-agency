"""Immutable additive Inbox retry state; no rewriting historical notes."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration


_BYTES = (Path(__file__).with_name("schema_versions") / "inbox_recovery_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def apply(conn):
    await conn.execute(text(CONTRACT["sql"]))
    await _verify_columns(conn)
    await conn.execute(text(CONTRACT["index_sql"]))


async def _verify_columns(conn):
    rows = (await conn.execute(text("""
        SELECT column_name, udt_name, is_nullable, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='inbox_notes'
    """))).mappings().all()
    columns = {r["column_name"]: [r["udt_name"], r["is_nullable"] == "YES",
                                r["character_maximum_length"]] for r in rows}
    for name, expected in CONTRACT["columns"].items():
        if columns.get(name) != expected:
            raise RuntimeError(f"Unsupported schema: inbox_notes.{name}")


async def verify(conn):
    await _verify_columns(conn)
    index = (await conn.execute(text("""
        SELECT i.indisvalid, i.indisready, i.indisunique, i.indnatts,
               pg_get_indexdef(i.indexrelid,1,true) AS first_key,
               pg_get_indexdef(i.indexrelid,2,true) AS second_key,
               pg_get_expr(i.indpred,i.indrelid) AS predicate, am.amname
        FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_am am ON am.oid=idx.relam
        WHERE i.indexrelid=to_regclass('public.ix_inbox_pending_attempt')
          AND i.indrelid='public.inbox_notes'::regclass
    """))).mappings().one_or_none()
    if not index or not (
        index["indisvalid"] and index["indisready"] and not index["indisunique"]
        and index["indnatts"] == 2 and index["amname"] == "btree"
        and index["first_key"] == "COALESCE(classification_next_attempt_at, updated_at)"
        and index["second_key"] == "id"
        and index["predicate"] == "(status = 'pending'::inboxnotestatus)"
    ):
        raise RuntimeError("Unsupported schema: inbox_notes pending attempt index")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
