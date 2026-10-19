"""Fase 0 de Agency 2.0: retira las tablas y columnas de los módulos borrados.

Es el único paso destructivo del plan. Borra las tablas de invitations, vault,
resources, evidence, reports, automations y my_week, y las columnas
decorativas del cliente y ``users.invited_by``. Sin CASCADE: si algo que no
está en el contrato depende todavía de ellas, el paso falla y no se aplica.

P12 deja de exigir estos elementos sólo cuando ya no existen
(``schema_baseline`` lee ``RETIRED_TABLES`` / ``RETIRED_COLUMNS``), así que la
verificación de despliegue sigue pasando antes y después de este paso.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration

_BYTES = (Path(__file__).with_name("schema_versions") / "phase0_retirement_v1.json").read_bytes()
CONTRACT = json.loads(_BYTES)
RETIRED_TABLES = frozenset(CONTRACT["drop_tables"])
RETIRED_COLUMNS = frozenset(
    (table, column) for table, columns in CONTRACT["drop_columns"].items() for column in columns
)


async def apply(conn):
    # Nombres sólo del contrato publicado e inmutable.
    for table in CONTRACT["drop_tables"]:
        await conn.execute(text(f"DROP TABLE IF EXISTS public.{table}"))
    for table, columns in CONTRACT["drop_columns"].items():
        for column in columns:
            await conn.execute(text(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS {column}"))
    await verify(conn)


async def verify(conn):
    tables = set((await conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    ))).scalars())
    left = RETIRED_TABLES & tables
    if left:
        raise RuntimeError(f"Unsupported schema: retired tables still present: {', '.join(sorted(left))}")
    rows = (await conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ))).all()
    left_columns = RETIRED_COLUMNS & {(r[0], r[1]) for r in rows}
    if left_columns:
        names = ", ".join(f"{t}.{c}" for t, c in sorted(left_columns))
        raise RuntimeError(f"Unsupported schema: retired columns still present: {names}")


MIGRATION = Migration(CONTRACT["version"], hashlib.sha256(_BYTES).hexdigest(), apply, verify)
