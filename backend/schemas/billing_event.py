from __future__ import annotations

from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel
from backend.db.models import BillingEventType


class BillingEventCreate(BaseModel):
    event_type: BillingEventType
    amount: Optional[float] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    event_date: date


class BillingEventResponse(BaseModel):
    id: int
    client_id: int
    event_type: BillingEventType
    amount: Optional[float] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    event_date: date
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BillingStatusResponse(BaseModel):
    billing_cycle: Optional[str] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[str] = None
    last_invoiced_date: Optional[str] = None
    days_until_invoice: Optional[int] = None
    is_overdue: bool
    monthly_fee: Optional[float] = None
    last_payment_date: Optional[str] = None
    last_payment_amount: Optional[float] = None
