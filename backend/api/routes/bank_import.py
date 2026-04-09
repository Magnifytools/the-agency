"""Bank statement import routes — parse CSV, match with invoices, apply."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User
from backend.api.deps import require_admin
from backend.services.bank_matcher import parse_bank_csv, match_transactions, apply_matches

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/finance/bank-import", tags=["bank-import"])


class BankPreviewRequest(BaseModel):
    content: str


class MatchApplyRequest(BaseModel):
    matches: list[dict]


@router.post("/preview")
async def preview_bank_statement(
    body: BankPreviewRequest,
    _user: User = Depends(require_admin),
):
    """Parse a bank statement CSV and return transactions."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="CSV vacío")

    try:
        transactions = parse_bank_csv(body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "transactions": transactions,
        "total": len(transactions),
        "income_count": sum(1 for t in transactions if t.get("is_income")),
        "expense_count": sum(1 for t in transactions if not t.get("is_income")),
    }


@router.post("/match")
async def match_bank_transactions(
    body: BankPreviewRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Parse CSV and match income transactions with pending invoices."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="CSV vacío")

    try:
        transactions = parse_bank_csv(body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    matched = await match_transactions(db, transactions)

    matched_count = sum(1 for t in matched if t.get("match"))
    return {
        "transactions": matched,
        "total": len(matched),
        "matched": matched_count,
        "unmatched": len(matched) - matched_count,
    }


@router.post("/apply")
async def apply_bank_matches(
    body: MatchApplyRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Apply confirmed matches — mark Income records as cobrado."""
    if not body.matches:
        raise HTTPException(status_code=400, detail="No hay matches para aplicar")

    applied = await apply_matches(db, body.matches)
    return {"ok": True, "applied": applied}
