"""
Holded API Client
Base URL: https://api.holded.com/api/
Auth: Header key con API key
Docs: https://developers.holded.com/reference
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

HOLDED_BASE = "https://api.holded.com/api"
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_BACKOFF = 2  # seconds


class HoldedError(Exception):
    """Custom error for Holded API failures."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Holded API error {status_code}: {detail}")


class HoldedClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"key": api_key, "Content-Type": "application/json"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        raw: bool = False,
    ) -> dict | list | bytes:
        url = f"{HOLDED_BASE}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    resp = await client.request(
                        method, url, headers=self.headers, json=json, params=params
                    )

                if resp.status_code == 429:
                    wait = RETRY_BACKOFF * (attempt + 1)
                    logger.warning("Holded rate limit hit, retrying in %ds", wait)
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    detail = resp.text[:500]
                    logger.error("Holded %s %s → %d: %s", method, path, resp.status_code, detail)
                    raise HoldedError(resp.status_code, detail)

                if raw:
                    return resp.content
                return resp.json()

            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning("Holded request error (attempt %d): %s", attempt + 1, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF)

        raise HoldedError(0, f"Request failed after retries: {last_exc}")

    # ── Contactos ──────────────────────────────────────────
    async def list_contacts(self) -> list[dict]:
        return await self._request("GET", "/invoicing/v1/contacts")

    async def create_contact(self, data: dict) -> dict:
        return await self._request("POST", "/invoicing/v1/contacts", json=data)

    async def get_contact(self, contact_id: str) -> dict:
        return await self._request("GET", f"/invoicing/v1/contacts/{contact_id}")

    async def update_contact(self, contact_id: str, data: dict) -> dict:
        return await self._request("PUT", f"/invoicing/v1/contacts/{contact_id}", json=data)

    # ── Facturas (Documents tipo 'invoice') ────────────────
    async def list_invoices(self) -> list[dict]:
        return await self._request("GET", "/invoicing/v1/documents/invoice")

    async def get_invoice(self, invoice_id: str) -> dict:
        return await self._request("GET", f"/invoicing/v1/documents/invoice/{invoice_id}")

    async def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return await self._request(
            "GET", f"/invoicing/v1/documents/invoice/{invoice_id}/pdf", raw=True
        )

    # ── Gastos (Documents tipo 'purchase') ─────────────────
    async def list_expenses(self) -> list[dict]:
        return await self._request("GET", "/invoicing/v1/documents/purchase")

    # ── Impuestos ──────────────────────────────────────────
    async def get_taxes(self) -> list[dict]:
        return await self._request("GET", "/invoicing/v1/taxes")

    # ── Tesoreria ──────────────────────────────────────────
    async def list_treasuries(self) -> list[dict]:
        return await self._request("GET", "/invoicing/v1/treasury")

    # ── Test connection ────────────────────────────────────
    async def test_connection(self) -> bool:
        """Quick test: try listing contacts. Returns True if OK."""
        try:
            await self.list_contacts()
            return True
        except HoldedError:
            return False
