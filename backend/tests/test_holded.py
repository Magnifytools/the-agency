"""Tests for Holded integration endpoints.

Covers:
- Config → 200
- Sync status → 200
- Auth required → 401
- Admin required for sync
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.routes import holded
from backend.db.models import HoldedInvoiceCache
from backend.services.temporal import business_today


@pytest.mark.asyncio
class TestHoldedAuth:
    """Auth required for /api/holded"""

    async def test_holded_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/holded/config")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestHoldedConfig:
    """GET /api/holded/config"""

    async def test_config_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/config")
        assert resp.status_code == 200

    async def test_sync_status_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/sync/status")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestHoldedInvoices:
    """GET /api/holded/invoices"""

    async def test_list_invoices_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/invoices")
        assert resp.status_code == 200

    async def test_list_invoices_with_filters(self, admin_client):
        resp = await admin_client.get(
            "/api/holded/invoices",
            params={"page": 1, "page_size": 10},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestHoldedSync:
    """POST /api/holded/sync/* — admin only"""

    async def test_sync_contacts_member_forbidden(self, member_client):
        resp = await member_client.post("/api/holded/sync/contacts")
        assert resp.status_code == 403


@pytest.mark.parametrize(
    ("pending", "paid", "due", "expected"),
    [
        (0, 120, date(2026, 9, 1), "paid"),
        (0, 125, date(2026, 9, 1), "paid"),
        (80, 40, date(2026, 9, 22), "pending"),
        (80, 40, date(2026, 9, 20), "overdue"),
        (120, 0, date(2026, 9, 20), "overdue"),
        (0, 0, date(2026, 9, 20), "unknown"),
    ],
)
def test_invoice_status_uses_outstanding_balance(monkeypatch, pending, paid, due, expected):
    monkeypatch.setattr(holded, "business_today", lambda: date(2026, 9, 21))
    invoice = {"total": 120, "paymentsPending": pending, "paymentsTotal": paid}
    assert holded._invoice_payment_status(invoice, due) == expected


@pytest.mark.parametrize(
    "invoice",
    [
        {"total": 120, "paymentsTotal": 120},
        {"total": 120, "paymentsPending": 0},
        {"total": 120, "paymentsPending": "bad", "paymentsTotal": 120},
        {"total": 120, "paymentsPending": float("nan"), "paymentsTotal": 120},
        {"total": 120, "paymentsPending": -1, "paymentsTotal": 120},
        {"total": 120, "paymentsPending": 121, "paymentsTotal": 0},
        {"total": 120, "paymentsPending": 20, "paymentsTotal": 120},
        {"total": 120, "paymentsPending": 0, "paymentsTotal": True},
    ],
)
def test_invoice_status_keeps_incomplete_or_invalid_balances_unknown(invoice):
    assert holded._invoice_payment_status(invoice, date(2026, 9, 1)) == "unknown"


def test_invoice_status_uses_madrid_civil_day(monkeypatch):
    instant = datetime(2026, 9, 20, 22, 30, tzinfo=timezone.utc)
    assert business_today(now=instant) == date(2026, 9, 21)
    monkeypatch.setattr(holded, "business_today", lambda: business_today(now=instant))
    invoice = {"total": 120, "paymentsPending": 80, "paymentsTotal": 40}
    assert holded._invoice_payment_status(invoice, date(2026, 9, 20)) == "overdue"


@pytest.mark.asyncio
async def test_invoice_sync_updates_only_holded_cache(monkeypatch):
    invoice = {
        "id": "holded-1", "total": 120, "paymentsPending": 0,
        "paymentsTotal": 120, "dueDate": "2026-09-01", "docNumber": "F-1",
    }
    monkeypatch.setattr(
        holded, "_get_holded_client",
        lambda: SimpleNamespace(list_invoices=AsyncMock(return_value=[invoice])),
    )
    session = AsyncMock()
    session.add = MagicMock()
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None
    session.execute.return_value = query_result

    result = await holded.sync_invoices(session=session, user=None)

    assert result.status == "success"
    cache = [call.args[0] for call in session.add.call_args_list
             if isinstance(call.args[0], HoldedInvoiceCache)]
    assert len(cache) == 1
    assert cache[0].status == "paid"
    assert all("income" not in str(call.args[0]).lower()
               for call in session.execute.call_args_list)
    session.commit.assert_awaited_once()
