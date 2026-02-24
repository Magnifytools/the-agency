from __future__ import annotations
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel


class ForecastCreate(BaseModel):
    month: date
    projected_income: float = 0.0
    projected_expenses: float = 0.0
    projected_taxes: float = 0.0
    projected_profit: float = 0.0
    confidence: float = 0.5
    notes: str = ""


class ForecastUpdate(BaseModel):
    month: Optional[date] = None
    projected_income: Optional[float] = None
    projected_expenses: Optional[float] = None
    projected_taxes: Optional[float] = None
    projected_profit: Optional[float] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None


class ForecastResponse(BaseModel):
    id: int
    month: date
    projected_income: float
    projected_expenses: float
    projected_taxes: float
    projected_profit: float
    confidence: float
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ForecastVsActual(BaseModel):
    month: date
    projected_income: float
    actual_income: float
    projected_expenses: float
    actual_expenses: float
    projected_profit: float
    actual_profit: float


class RunwayResponse(BaseModel):
    current_cash: float
    avg_monthly_burn: float
    runway_months: float
    runway_date: Optional[date] = None
