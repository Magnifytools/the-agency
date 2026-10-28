"""Accesos: notas cifradas y fecha del último cambio de contraseña.

- Las notas existentes (hasta ahora en claro) se cifran aquí con
  ``encrypt_vault_secret``, igual que la contraseña, y un CHECK impide volver a
  guardarlas en claro. Una nota vacía pasa a NULL. Es idempotente: lo que ya
  descifra con la clave actual no se toca.
- ``secret_changed_at`` dice cuándo se cambió la contraseña por última vez (la
  vista de salida de alguien la compara con lo que esa persona vio). Se rellena
  con el último "update" del registro que cambió la contraseña, o con el alta.
- La acción "notes" (alguien abrió las notas) entra en el registro.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "credentials_notes_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)


def _encrypted(value: str) -> bool:
    if not value.startswith("v1:"):
        return False
    try:
        decrypt_vault_secret(value)
    except ValueError:
        return False
    return True


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
    for statement in CONTRACT["before"]:
        await conn.execute(text(statement))
    rows = (await conn.execute(text("SELECT id, notes FROM credentials WHERE notes IS NOT NULL"))).all()
    for credential_id, notes in rows:
        if _encrypted(notes):
            continue
        value = encrypt_vault_secret(notes) if notes.strip() else None
        await conn.execute(text("UPDATE credentials SET notes = :notes WHERE id = :id"),
                           {"notes": value, "id": credential_id})
    for statement in CONTRACT["after"]:
        await conn.execute(text(statement))
    await verify(conn)


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
