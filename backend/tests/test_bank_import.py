"""Tests for bank statement import routes and matching logic."""
from __future__ import annotations

import pytest
from backend.services.bank_matcher import parse_bank_csv, _parse_date, _parse_amount


class TestBankCsvParser:
    def test_parse_semicolon_csv(self):
        csv = "fecha;concepto;importe\n01/04/2026;Pago cliente;1500,00\n02/04/2026;Gasto oficina;-200,50"
        txs = parse_bank_csv(csv)
        assert len(txs) == 2
        assert txs[0]["date"] == "2026-04-01"
        assert txs[0]["amount"] == 1500.0
        assert txs[0]["is_income"] is True
        assert txs[1]["amount"] == -200.5
        assert txs[1]["is_income"] is False

    def test_parse_comma_csv(self):
        csv = "fecha,concepto,importe\n2026-04-01,Payment,2000.00"
        txs = parse_bank_csv(csv)
        assert len(txs) == 1
        assert txs[0]["amount"] == 2000.0

    def test_parse_spanish_amount_format(self):
        csv = "fecha;concepto;importe\n01/04/2026;Cobro;1.234,56"
        txs = parse_bank_csv(csv)
        assert txs[0]["amount"] == 1234.56

    def test_empty_csv_returns_empty(self):
        assert parse_bank_csv("") == []
        assert parse_bank_csv("header\n") == []

    def test_missing_columns_raises(self):
        with pytest.raises(ValueError, match="fecha/importe"):
            parse_bank_csv("col_a;col_b\n1;2")


class TestDateParser:
    def test_dd_mm_yyyy(self):
        assert _parse_date("01/04/2026").isoformat() == "2026-04-01"

    def test_yyyy_mm_dd(self):
        assert _parse_date("2026-04-01").isoformat() == "2026-04-01"

    def test_invalid_returns_none(self):
        assert _parse_date("not a date") is None


class TestAmountParser:
    def test_spanish_format(self):
        assert float(_parse_amount("1.234,56")) == 1234.56

    def test_plain_decimal(self):
        assert float(_parse_amount("1500.00")) == 1500.0

    def test_euro_symbol(self):
        assert float(_parse_amount("500,00€")) == 500.0

    def test_empty_returns_none(self):
        assert _parse_amount("") is None


@pytest.mark.asyncio
class TestBankImportEndpoints:
    async def test_preview_returns_transactions(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/bank-import/preview",
            json={"content": "fecha;concepto;importe\n01/04/2026;Pago;1500,00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["income_count"] == 1

    async def test_preview_empty_csv(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/bank-import/preview",
            json={"content": ""},
        )
        assert resp.status_code == 400

    async def test_match_returns_results(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/bank-import/match",
            json={"content": "fecha;concepto;importe\n01/04/2026;Pago;1500,00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "transactions" in data
        assert "matched" in data

    async def test_apply_empty_matches(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/bank-import/apply",
            json={"matches": []},
        )
        assert resp.status_code == 400
