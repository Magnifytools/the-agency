"""Paso aditivo: periodos de resumen saltados (vacaciones, ya no se hace...).

Una fila por (cliente, periodo) que no se va a entregar: cuenta como resuelto
para los avisos, "sin entregar" y el estado del cliente. "Volver a pendiente"
la borra. Ver `DigestPeriodSkip` en `db/models.py`.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "digest_period_skips_v1.json").read_bytes()
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
    for fk in CONTRACT["foreign_keys"]:
        found = (await conn.execute(text("""
            SELECT 1 FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
            WHERE c.conrelid=CAST(:table AS regclass) AND c.contype='f'
              AND array_length(c.conkey, 1)=1 AND a.attname=:column
              AND c.confrelid=CAST(:references AS regclass) AND c.confdeltype::text=:on_delete
        """), {"table": f"public.{fk['table']}", "column": fk["column"],
               "references": f"public.{fk['references']}", "on_delete": fk["on_delete"]})).first()
        if found is None:
            raise RuntimeError(f"Unsupported schema: {fk['table']}.{fk['column']} foreign key")
    for table, names in CONTRACT["check_constraints"].items():
        present = set((await conn.execute(text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid=CAST(:table AS regclass) AND contype='c'
        """), {"table": f"public.{table}"})).scalars().all())
        missing = [name for name in names if name not in present]
        if missing:
            raise RuntimeError(f"Unsupported schema: {table} checks {', '.join(missing)}")
    for table, constraints in CONTRACT["unique_constraints"].items():
        for name, expected in constraints.items():
            found = (await conn.execute(text("""
                SELECT ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,p)
                             JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n
                             ORDER BY k.p) AS columns
                FROM pg_constraint c
                WHERE c.conrelid=CAST(:table AS regclass) AND c.contype='u' AND c.conname=:name
            """), {"table": f"public.{table}", "name": name})).scalars().all()
            if found != [expected]:
                raise RuntimeError(f"Unsupported schema: {table} unique {name}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
