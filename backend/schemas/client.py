from __future__ import annotations
from typing import Optional

from datetime import date, datetime
from pydantic import BaseModel
from backend.db.models import ContractType, ClientStatus, BillingCycle


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType = ContractType.monthly
    monthly_budget: Optional[float] = None
    status: ClientStatus = ClientStatus.active
    notes: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    billing_cycle: Optional[BillingCycle] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[date] = None
    last_invoiced_date: Optional[date] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: Optional[ContractType] = None
    monthly_budget: Optional[float] = None
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    billing_cycle: Optional[BillingCycle] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[date] = None
    last_invoiced_date: Optional[date] = None
    engine_project_id: Optional[int] = None


class ClientResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType
    monthly_budget: Optional[float] = None
    status: ClientStatus
    notes: Optional[str] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    billing_cycle: Optional[BillingCycle] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[date] = None
    last_invoiced_date: Optional[date] = None
    engine_project_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
