from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import BalanceSnapshot, User
from backend.schemas.balance import BalanceSnapshotCreate, BalanceSnapshotResponse
from backend.api.deps import require_module
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/finance/balance", tags=["finance-balance"])


@router.get("/latest", response_model=Optional[BalanceSnapshotResponse])
async def get_latest_balance(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("finance_income")),
):
    r = await db.execute(
        select(BalanceSnapshot).order_by(BalanceSnapshot.date.desc()).limit(1)
    )
    return r.scalars().first()


@router.post("", response_model=BalanceSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_balance_snapshot(
    data: BalanceSnapshotCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("finance_income", write=True)),
):
    item = BalanceSnapshot(**data.model_dump())
    db.add(item)
    await db.commit()
    await safe_refresh(db, item, log_context="balance")
    return item


@router.get("", response_model=list[BalanceSnapshotResponse])
async def list_balance_snapshots(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("finance_income")),
):
    r = await db.execute(
        select(BalanceSnapshot).order_by(BalanceSnapshot.date.desc()).limit(12)
    )
    return list(r.scalars().all())
