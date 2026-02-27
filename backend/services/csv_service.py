from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Optional


KNOWN_DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y"]


def parse_csv(content: str, delimiter: str = ",") -> list[dict]:
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    return [dict(row) for row in reader]


def detect_delimiter(content: str) -> str:
    first_line = content.split("\n")[0]
    for delim in [",", ";", "\t", "|"]:
        if delim in first_line:
            return delim
    return ","


def detect_columns(rows: list[dict]) -> dict:
    if not rows:
        return {}
    headers = list(rows[0].keys())
    mapping = {}
    date_keywords = ["fecha", "date", "dia"]
    desc_keywords = ["descripcion", "concepto", "description", "detalle", "referencia"]
    amount_keywords = ["importe", "amount", "cantidad", "monto", "total"]
    category_keywords = ["categoria", "category", "tipo", "type"]
    for header in headers:
        h = header.lower().strip()
        if any(k in h for k in date_keywords):
            mapping["date"] = header
        elif any(k in h for k in amount_keywords):
            mapping["amount"] = header
        elif any(k in h for k in desc_keywords):
            mapping["description"] = header
        elif any(k in h for k in category_keywords):
            mapping["category"] = header
    return mapping


def parse_date(value: str) -> Optional[str]:
    value = value.strip()
    for fmt in KNOWN_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_amount(value: str) -> Optional[float]:
    if value is None:
        return None

    normalized = re.sub(r"[^\d,.\-()]", "", value.strip())
    if not normalized:
        return None

    is_negative = False
    if normalized.startswith("(") and normalized.endswith(")"):
        is_negative = True
        normalized = normalized[1:-1]

    if normalized.startswith("-"):
        is_negative = True
        normalized = normalized[1:]

    if not normalized:
        return None

    comma_idx = normalized.rfind(",")
    dot_idx = normalized.rfind(".")

    if comma_idx != -1 and dot_idx != -1:
        # Decimal separator is usually the last one in locale-formatted numbers.
        decimal_sep = "," if comma_idx > dot_idx else "."
        thousands_sep = "." if decimal_sep == "," else ","
        normalized = normalized.replace(thousands_sep, "")
        normalized = normalized.replace(decimal_sep, ".")
    elif comma_idx != -1:
        parts = normalized.split(",")
        if len(parts) > 2:
            normalized = "".join(parts[:-1]) + "." + parts[-1]
        elif len(parts[-1]) in (0, 1, 2):
            normalized = normalized.replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif dot_idx != -1:
        parts = normalized.split(".")
        if len(parts) > 2:
            normalized = "".join(parts[:-1]) + "." + parts[-1]
        elif len(parts[-1]) not in (0, 1, 2):
            normalized = normalized.replace(".", "")

    try:
        amount = float(normalized)
        return -amount if is_negative else amount
    except ValueError:
        return None


def process_csv_preview(content: str) -> dict:
    delimiter = detect_delimiter(content)
    rows = parse_csv(content, delimiter)
    if not rows:
        return {"headers": [], "rows": [], "total_rows": 0, "detected_delimiter": delimiter}

    headers = list(rows[0].keys())
    preview_rows = [[row.get(h, "") for h in headers] for row in rows[:20]]

    return {
        "headers": headers,
        "rows": preview_rows,
        "total_rows": len(rows),
        "detected_delimiter": delimiter,
    }
