from __future__ import annotations
from typing import Literal, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field

TaxStatus = Literal["pendiente", "pagado", "aplazado"]


class TaxCreate(BaseModel):
    name: str
    model: str = ""
    period: str = ""
    year: int = Field(ge=2000, le=2100)
    base_amount: float = 0.0
    tax_rate: float = Field(default=0.0, ge=0, le=100)
    tax_amount: float = 0.0
    status: TaxStatus = "pendiente"
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: str = ""


class TaxUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    period: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=2000, le=2100)
    base_amount: Optional[float] = None
    tax_rate: Optional[float] = Field(default=None, ge=0, le=100)
    tax_amount: Optional[float] = None
    status: Optional[TaxStatus] = None
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class TaxResponse(BaseModel):
    id: int
    name: str
    model: str
    period: str
    year: int
    base_amount: float
    tax_rate: float
    tax_amount: float
    status: str
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TaxCalendarItem(BaseModel):
    model: str
    name: str
    period: str
    due_date: date
    status: str


class QuarterlyVatResult(BaseModel):
    period: str
    year: int
    vat_collected: float
    vat_paid: float
    vat_balance: float
    income_base: float
    expense_base: float
