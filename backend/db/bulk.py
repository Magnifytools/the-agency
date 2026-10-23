"""Inserciones de muchas filas en un solo INSERT ... VALUES.

asyncpg no acepta más de 32.767 parámetros por consulta, y SQLAlchemy manda
uno por columna y fila, incluidas las columnas con default de Python que la
fila no trae (`gsc_query_monthly.source`). El lote se dimensiona por las
columnas de la TABLA, no por las claves del dict: 5.000 filas de 7 columnas
son 35.000 y la consulta revienta (Sage, 23 oct 2026).
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TypeVar

POSTGRES_MAX_PARAMS = 32767

T = TypeVar("T")


def insert_chunks(model, values: Sequence[T]) -> Iterator[Sequence[T]]:
    """Trozos de `values` que caben en un INSERT de `model`."""
    size = max(1, POSTGRES_MAX_PARAMS // len(model.__table__.columns))
    for i in range(0, len(values), size):
        yield values[i:i + size]
