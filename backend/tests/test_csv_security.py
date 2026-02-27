from __future__ import annotations

import pytest

from backend.services.csv_service import parse_amount
from backend.services.csv_utils import sanitize_csv_cell


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1234,56", 1234.56),
        ("1234.56", 1234.56),
        ("1.234", 1234.0),
        ("1,234", 1234.0),
        ("-150,75", -150.75),
        ("(150,75)", -150.75),
        ("€ 2.500,00", 2500.0),
    ],
)
def test_parse_amount_handles_locale_and_sign(raw: str, expected: float):
    assert parse_amount(raw) == expected


def test_parse_amount_invalid_returns_none():
    assert parse_amount("abc") is None
    assert parse_amount("") is None


def test_sanitize_csv_cell_blocks_formula_prefix():
    assert sanitize_csv_cell("=CMD()") == "'=CMD()"
    assert sanitize_csv_cell(" +SUM(A1:A2)") == "' +SUM(A1:A2)"
    assert sanitize_csv_cell("@malicious") == "'@malicious"


def test_sanitize_csv_cell_keeps_numeric_values():
    assert sanitize_csv_cell(-123.45) == -123.45
    assert sanitize_csv_cell(42) == 42


@pytest.mark.asyncio
async def test_billing_export_rejects_invalid_month(admin_client):
    response = await admin_client.get("/api/billing/export?format=json&year=2026&month=13")
    assert response.status_code == 422
