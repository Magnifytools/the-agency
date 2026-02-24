from __future__ import annotations
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel


class FinancialInsightResponse(BaseModel):
    id: int
    type: str
    title: str
    description: str
    severity: str
    is_read: bool
    is_dismissed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdvisorTaskCreate(BaseModel):
    source_key: str
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: Optional[date] = None


class AdvisorTaskResponse(BaseModel):
    id: int
    source_key: str
    title: str
    description: str
    status: str
    priority: str
    due_date: Optional[date] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdvisorAiBriefResponse(BaseModel):
    id: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    content: str
    model: str
    provider: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdvisorOverview(BaseModel):
    total_income_month: float
    total_expenses_month: float
    net_profit_month: float
    margin_pct: float
    pending_taxes: float
    next_tax_deadline: Optional[date] = None
    unread_insights: int
    open_tasks: int
    cash_runway_months: Optional[float] = None
