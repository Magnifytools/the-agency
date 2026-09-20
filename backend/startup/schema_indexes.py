"""Read-only verification of frozen unique-index contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_HOLIDAY_COLUMNS = ("date", "region", "locality")
_HOLIDAY_LEGACY_EXPRESSIONS = (
    "date",
    "COALESCE(region, ''::character varying)",
    "COALESCE(locality, ''::character varying)",
)


def _expected_keys(contract: Mapping[str, object]) -> tuple[tuple[str, ...], ...]:
    columns = tuple(str(column) for column in contract["columns"])
    if contract["table"] == "company_holidays" and columns == _HOLIDAY_COLUMNS:
        return (columns, _HOLIDAY_LEGACY_EXPRESSIONS)
    return (columns,)


async def check_unique_indexes(
    conn: AsyncConnection,
    contracts: Iterable[Mapping[str, object]],
) -> None:
    """Require every unique-index contract by semantics, never by index name.

    Key expressions include only ``indnkeyatts`` positions, so optional INCLUDE
    columns neither satisfy nor invalidate the ordered key contract.
    """
    contracts = tuple(contracts)
    tables = sorted({str(contract["table"]) for contract in contracts})
    rows = (await conn.execute(text("""
        SELECT t.relname AS table_name,i.indisunique,i.indisvalid,i.indisready,
               coalesce(pg_get_expr(i.indpred, i.indrelid), '') AS predicate,
               ARRAY(
                   SELECT pg_get_indexdef(i.indexrelid, position, true)
                   FROM generate_series(1, i.indnkeyatts) AS position
                   ORDER BY position
               ) AS keys
        FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='public' AND t.relname=ANY(CAST(:tables AS text[]))
    """), {"tables": tables})).mappings().all()
    for contract in contracts:
        table = str(contract["table"])
        predicate = str(contract.get("predicate", ""))
        expected_keys = _expected_keys(contract)
        if any(
            row["table_name"] == table
            and row["indisunique"]
            and row["indisvalid"]
            and row["indisready"]
            and row["predicate"] == predicate
            and tuple(row["keys"]) in expected_keys
            for row in rows
        ):
            continue
        columns = ",".join(str(column) for column in contract["columns"])
        raise RuntimeError(
            f"Required unique index is missing or invalid: {table}({columns})"
        )
