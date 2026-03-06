from __future__ import annotations
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, Field


class IncomeCreate(BaseModel):
    date: date
    description: str
    amount: float = Field(ge=0)
    type: str = "factura"
    client_id: Optional[int] = None
    invoice_number: str = ""
    vat_rate: float = 21.0
    vat_amount: float = 0.0
    status: str = "cobrado"
    notes: str = ""
    due_date: Optional[date] = None


class IncomeUpdate(BaseModel):
    date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    type: Optional[str] = None
    client_id: Optional[int] = None
    invoice_number: Optional[str] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    due_date: Optional[date] = None


class IncomeResponse(BaseModel):
    id: int
    date: date
    description: str
    amount: float
    type: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    invoice_number: str
    vat_rate: float
    vat_amount: float
    status: str
    notes: str
    due_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
