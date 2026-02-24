from __future__ import annotations

import csv
import io
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
    value = value.strip().replace("\u20ac", "").replace("$", "").strip()
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        original = value.replace(".", ",").replace(",", ".", 1)
        try:
            return float(original)
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
