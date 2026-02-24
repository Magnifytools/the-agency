from __future__ import annotations
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel


class ExpenseCategoryCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "#6B7280"


class ExpenseCategoryResponse(BaseModel):
    id: int
    name: str
    description: str
    color: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseCreate(BaseModel):
    date: date
    description: str
    amount: float
    category_id: Optional[int] = None
    is_recurring: bool = False
    recurrence_period: str = ""
    vat_rate: float = 21.0
    vat_amount: float = 0.0
    is_deductible: bool = True
    supplier: str = ""
    notes: str = ""


class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[int] = None
    is_recurring: Optional[bool] = None
    recurrence_period: Optional[str] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    is_deductible: Optional[bool] = None
    supplier: Optional[str] = None
    notes: Optional[str] = None


class ExpenseResponse(BaseModel):
    id: int
    date: date
    description: str
    amount: float
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    is_recurring: bool
    recurrence_period: str
    vat_rate: float
    vat_amount: float
    is_deductible: bool
    supplier: str
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
