from __future__ import annotations

import csv
from numbers import Number
from typing import Any, Iterable, Iterator

from fastapi.responses import StreamingResponse


_DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def sanitize_csv_cell(value: Any) -> Any:
    """Prevent CSV formula injection for user-controlled string values."""
    if value is None:
        return ""
    if isinstance(value, Number):
        return value

    text = str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in _DANGEROUS_PREFIXES:
        return f"'{text}"
    return text


def sanitize_csv_row(values: Iterable[Any]) -> list[Any]:
    return [sanitize_csv_cell(value) for value in values]


class _CsvBuffer:
    def write(self, value: str) -> str:
        return value


def iter_sanitized_csv(header: Iterable[Any], rows: Iterable[Iterable[Any]]) -> Iterator[str]:
    writer = csv.writer(_CsvBuffer())
    yield writer.writerow(sanitize_csv_row(header))
    for row in rows:
        yield writer.writerow(sanitize_csv_row(row))


def build_csv_response(
    filename: str,
    header: Iterable[Any],
    rows: Iterable[Iterable[Any]],
) -> StreamingResponse:
    return StreamingResponse(
        iter_sanitized_csv(header, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
