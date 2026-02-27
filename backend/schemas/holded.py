"""Schemas for Holded integration."""
from datetime import date as dt_date, datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ── Sync ───────────────────────────────────────────────────

class SyncLogResponse(BaseModel):
    id: int
    sync_type: str
    status: str
    records_synced: int
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SyncStatusResponse(BaseModel):
    contacts: Optional[SyncLogResponse] = None
    invoices: Optional[SyncLogResponse] = None
    expenses: Optional[SyncLogResponse] = None


class SyncResult(BaseModel):
    sync_type: str
    status: str
    records_synced: int
    error_message: Optional[str] = None


# ── Invoices ───────────────────────────────────────────────

class HoldedInvoiceResponse(BaseModel):
    id: int
    holded_id: str
    client_id: Optional[int] = None
    contact_name: Optional[str] = None
    invoice_number: Optional[str] = None
    date: Optional[dt_date] = None
    due_date: Optional[dt_date] = None
    total: float = 0
    subtotal: float = 0
    tax: float = 0
    status: Optional[str] = None
    currency: str = "EUR"
    synced_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("date", "due_date", mode="before")
    @classmethod
    def parse_date_permissive(cls, v):
        if v is None:
            return None
        if isinstance(v, dt_date):
            return v
        if isinstance(v, str):
            try:
                return dt_date.fromisoformat(v[:10])
            except (ValueError, IndexError):
                return None
        return None


# ── Expenses ───────────────────────────────────────────────

class HoldedExpenseResponse(BaseModel):
    id: int
    holded_id: str
    description: Optional[str] = None
    date: Optional[dt_date] = None
    total: float = 0
    subtotal: float = 0
    tax: float = 0
    category: Optional[str] = None
    supplier: Optional[str] = None
    status: Optional[str] = None
    synced_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("date", mode="before")
    @classmethod
    def parse_date_permissive(cls, v):
        if v is None:
            return None
        if isinstance(v, dt_date):
            return v
        if isinstance(v, str):
            try:
                return dt_date.fromisoformat(v[:10])
            except (ValueError, IndexError):
                return None
        return None


# ── Paginated responses ───────────────────────────────────

class HoldedInvoicePageResponse(BaseModel):
    items: list[HoldedInvoiceResponse]
    total: int
    page: int
    page_size: int


class HoldedExpensePageResponse(BaseModel):
    items: list[HoldedExpenseResponse]
    total: int
    page: int
    page_size: int


# ── Dashboard ──────────────────────────────────────────────

class MonthlyFinancials(BaseModel):
    month: str  # YYYY-MM
    income: float = 0
    expenses: float = 0
    profit: float = 0


class HoldedDashboardResponse(BaseModel):
    income_this_month: float = 0
    expenses_this_month: float = 0
    profit_this_month: float = 0
    income_ytd: float = 0
    expenses_ytd: float = 0
    profit_ytd: float = 0
    pending_invoices: list[HoldedInvoiceResponse] = []
    monthly_data: list[MonthlyFinancials] = []


# ── Config ─────────────────────────────────────────────────

class HoldedConfigResponse(BaseModel):
    api_key_configured: bool
    connection_healthy: bool = False
    last_sync_contacts: Optional[SyncLogResponse] = None
    last_sync_invoices: Optional[SyncLogResponse] = None
    last_sync_expenses: Optional[SyncLogResponse] = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
