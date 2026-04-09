"""Bank statement import — parse CSV and match transactions with invoices."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Income, Client

logger = logging.getLogger(__name__)


def parse_bank_csv(content: str) -> list[dict]:
    """Parse a bank statement CSV. Returns list of transactions.

    Handles common Spanish bank formats:
    - Columns: fecha, concepto, importe (or similar)
    - Semicolon or comma delimiters
    - Decimal comma (1.234,56) or decimal point
    """
    # Auto-detect delimiter
    delimiter = ";" if content.count(";") > content.count(",") else ","

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    if len(rows) < 2:
        return []

    headers = [h.strip().lower() for h in rows[0]]

    # Map common header names
    date_col = _find_col(headers, ["fecha", "date", "f.valor", "f. valor", "fecha valor", "fecha operación"])
    desc_col = _find_col(headers, ["concepto", "descripción", "description", "detalle", "movimiento"])
    amount_col = _find_col(headers, ["importe", "amount", "cantidad", "monto", "€"])

    if date_col is None or amount_col is None:
        raise ValueError(f"No se encontraron columnas de fecha/importe. Columnas: {headers}")

    transactions = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= max(date_col, amount_col):
            continue
        try:
            tx_date = _parse_date(row[date_col].strip())
            amount = _parse_amount(row[amount_col].strip())
            desc = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""

            if tx_date and amount is not None:
                transactions.append({
                    "row": i,
                    "date": tx_date.isoformat(),
                    "description": desc,
                    "amount": float(amount),
                    "is_income": amount > 0,
                })
        except Exception:
            continue

    return transactions


async def match_transactions(
    db: AsyncSession,
    transactions: list[dict],
) -> list[dict]:
    """Match bank transactions with pending Income records.

    Returns transactions with suggested matches.
    """
    results = []

    # Load all pending incomes
    pending_result = await db.execute(
        select(Income)
        .outerjoin(Client, Income.client_id == Client.id)
        .where(Income.status == "pendiente")
    )
    pending_incomes = pending_result.scalars().all()

    for tx in transactions:
        if not tx.get("is_income"):
            results.append({**tx, "match": None, "confidence": 0})
            continue

        amount = Decimal(str(tx["amount"]))
        tx_date = date.fromisoformat(tx["date"])
        best_match = None
        best_confidence = 0

        for inc in pending_incomes:
            confidence = 0
            inc_amount = inc.amount or Decimal("0")

            # Amount match (within 5%)
            if inc_amount > 0:
                diff_pct = abs(float(amount - inc_amount) / float(inc_amount)) * 100
                if diff_pct < 1:
                    confidence += 60
                elif diff_pct < 5:
                    confidence += 40
                else:
                    continue  # Skip if amount is too different

            # Date proximity (within 30 days)
            if inc.date:
                days_diff = abs((tx_date - inc.date).days)
                if days_diff < 7:
                    confidence += 25
                elif days_diff < 30:
                    confidence += 15

            # Description contains invoice number
            if inc.invoice_number and inc.invoice_number.lower() in tx.get("description", "").lower():
                confidence += 30

            # Description contains client name
            if inc.client and inc.client.name.lower() in tx.get("description", "").lower():
                confidence += 20

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = {
                    "income_id": inc.id,
                    "invoice_number": inc.invoice_number,
                    "client_name": inc.client.name if inc.client else None,
                    "amount": float(inc_amount),
                    "date": inc.date.isoformat() if inc.date else None,
                }

        results.append({
            **tx,
            "match": best_match if best_confidence >= 40 else None,
            "confidence": best_confidence,
        })

    return results


async def apply_matches(
    db: AsyncSession,
    matches: list[dict],
) -> int:
    """Apply confirmed matches — mark Income records as 'cobrado'. Returns count."""
    applied = 0
    for m in matches:
        income_id = m.get("income_id")
        if not income_id:
            continue
        result = await db.execute(
            select(Income).where(Income.id == income_id, Income.status == "pendiente")
        )
        income = result.scalar_one_or_none()
        if income:
            income.status = "cobrado"
            applied += 1
            logger.info("Bank match: Income %d marked as cobrado", income_id)

    await db.commit()
    return applied


# ── Parsing helpers ─────────────────────────────────────────

def _find_col(headers: list[str], candidates: list[str]) -> Optional[int]:
    for c in candidates:
        for i, h in enumerate(headers):
            if c in h:
                return i
    return None


def _parse_date(val: str) -> Optional[date]:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(val: str) -> Optional[Decimal]:
    # Remove currency symbols and spaces
    val = val.replace("€", "").replace("$", "").replace(" ", "").strip()
    if not val:
        return None
    # Handle Spanish format: 1.234,56 → 1234.56
    if "," in val and "." in val:
        val = val.replace(".", "").replace(",", ".")
    elif "," in val:
        val = val.replace(",", ".")
    try:
        return Decimal(val)
    except InvalidOperation:
        return None
