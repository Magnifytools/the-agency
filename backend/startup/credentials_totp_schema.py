"""Accesos: clave del autenticador (2FA) cifrada en cada acceso y la acción
"totp" (alguien pidió el código) en el registro.

Columna aditiva y NULL: los accesos existentes siguen igual. El CHECK, como el
de la contraseña, impide guardar la clave en claro. El CHECK de acciones se
cambia con el mismo nombre (lo comprueba `credentials_v1`).
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "credentials_totp_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


async def verify(conn):
    table, column, udt, nullable = CONTRACT["column"]
    row = (await conn.execute(text("""
        SELECT udt_name, is_nullable FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:table AND column_name=:column
    """), {"table": table, "column": column})).mappings().one_or_none()
    if row is None or row["udt_name"] != udt or (row["is_nullable"] == "YES") != nullable:
        raise RuntimeError(f"Unsupported schema: {table}.{column}")
    for name, (check_table, must_contain) in CONTRACT["checks"].items():
        definition = await conn.scalar(text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conname=:name AND conrelid=CAST(:table AS regclass) AND contype='c'
        """), {"name": name, "table": f"public.{check_table}"})
        if definition is None or must_contain not in definition:
            raise RuntimeError(f"Unsupported schema: {check_table} check {name}")


async def apply(conn):
    for statement in CONTRACT["statements"]:
        await conn.execute(text(statement))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
