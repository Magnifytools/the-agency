from __future__ import annotations
from typing import Optional

from pydantic import BaseModel


class DashboardOverview(BaseModel):
    active_clients: int
    pending_tasks: int
    in_progress_tasks: int
    hours_this_month: float
    total_budget: float
    total_cost: float
    margin: float
    margin_percent: float


class ClientProfitability(BaseModel):
    client_id: int
    client_name: str
    budget: float
    cost: float
    margin: float
    margin_percent: float
    estimated_minutes: int
    actual_minutes: int
    variance_minutes: int
    status: str  # profitable / at_risk / unprofitable


class ProfitabilityResponse(BaseModel):
    clients: list[ClientProfitability]


class TeamMemberSummary(BaseModel):
    user_id: int
    full_name: str
    hourly_rate: Optional[float]
    hours_this_month: float
    cost: float
    task_count: int
    clients_touched: int


class MonthlyCloseResponse(BaseModel):
    year: int
    month: int
    reviewed_numbers: bool
    reviewed_margin: bool
    reviewed_cash_buffer: bool
    reviewed_reinvestment: bool
    reviewed_debt: bool
    reviewed_taxes: bool
    reviewed_personal: bool
    responsible_name: str = ""
    notes: str = ""
    updated_at: Optional[str] = None


class MonthlyCloseUpdate(BaseModel):
    reviewed_numbers: Optional[bool] = None
    reviewed_margin: Optional[bool] = None
    reviewed_cash_buffer: Optional[bool] = None
    reviewed_reinvestment: Optional[bool] = None
    reviewed_debt: Optional[bool] = None
    reviewed_taxes: Optional[bool] = None
    reviewed_personal: Optional[bool] = None
    responsible_name: Optional[str] = None
    notes: Optional[str] = None


class FinancialSettingsResponse(BaseModel):
    tax_reserve: float
    credit_limit: float
    credit_used: float
    credit_utilization: float
    monthly_close_day: int
    credit_alert_pct: float
    tax_reserve_target_pct: float
    default_vat_rate: float
    corporate_tax_rate: float
    irpf_retention_rate: float
    cash_start: float
    advisor_expense_alert_pct: float
    advisor_margin_warning_pct: float
    ai_provider: str
    ai_model: str
    ai_api_url: str


class FinancialSettingsUpdate(BaseModel):
    tax_reserve: Optional[float] = None
    credit_limit: Optional[float] = None
    credit_used: Optional[float] = None
    monthly_close_day: Optional[int] = None
    credit_alert_pct: Optional[float] = None
    tax_reserve_target_pct: Optional[float] = None
    default_vat_rate: Optional[float] = None
    corporate_tax_rate: Optional[float] = None
    irpf_retention_rate: Optional[float] = None
    cash_start: Optional[float] = None
    advisor_expense_alert_pct: Optional[float] = None
    advisor_margin_warning_pct: Optional[float] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_api_url: Optional[str] = None
    ai_api_key: Optional[str] = None
