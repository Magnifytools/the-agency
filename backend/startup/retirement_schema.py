"""Pasos de retirada: borran tablas y columnas publicadas según su contrato.

Cada paso destructivo es un contrato JSON inmutable con ``drop_tables`` y
``drop_columns``. Sin CASCADE: si algo fuera del contrato depende todavía de
lo retirado, el paso falla y no se registra.

P12 deja de exigir lo retirado sólo cuando ya no existe: ``schema_baseline``
une los ``tables`` / ``columns`` de todos los pasos de su ``RETIREMENTS``, así
que la verificación de despliegue pasa antes y después de cada paso. Para
retirar algo más: contrato nuevo + módulo con ``Retirement(...)`` + añadirlo a
``RETIREMENTS`` en ``schema_baseline`` y al final de ``deployment_schema``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from backend.startup.schema_runner import Migration


class Retirement:
    def __init__(self, contract_name: str):
        data = (Path(__file__).with_name("schema_versions") / contract_name).read_bytes()
        self.contract = json.loads(data)
        self.tables = frozenset(self.contract["drop_tables"])
        self.columns = frozenset(
            (table, column)
            for table, columns in self.contract["drop_columns"].items()
            for column in columns
        )
        self.migration = Migration(
            self.contract["version"], hashlib.sha256(data).hexdigest(), self.apply, self.verify,
        )

    async def apply(self, conn):
        # Nombres sólo del contrato publicado e inmutable.
        for table in self.contract["drop_tables"]:
            await conn.execute(text(f"DROP TABLE IF EXISTS public.{table}"))
        for table, columns in self.contract["drop_columns"].items():
            for column in columns:
                await conn.execute(text(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS {column}"))
        await self.verify(conn)

    async def verify(self, conn):
        tables = set((await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ))).scalars())
        left = self.tables & tables
        if left:
            raise RuntimeError(f"Unsupported schema: retired tables still present: {', '.join(sorted(left))}")
        rows = (await conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
        ))).all()
        left_columns = self.columns & {(r[0], r[1]) for r in rows}
        if left_columns:
            names = ", ".join(f"{t}.{c}" for t, c in sorted(left_columns))
            raise RuntimeError(f"Unsupported schema: retired columns still present: {names}")
