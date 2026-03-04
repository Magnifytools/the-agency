from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel


class BalanceSnapshotCreate(BaseModel):
    date: date
    amount: float
    notes: str = ""


class BalanceSnapshotResponse(BaseModel):
    id: int
    date: date
    amount: float
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
