from __future__ import annotations
from typing import Optional

from datetime import date, datetime
from pydantic import BaseModel, Field
from backend.db.models import ContractType, ClientStatus, BillingCycle


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType = ContractType.monthly
    monthly_budget: Optional[float] = Field(None, ge=0)
    status: ClientStatus = ClientStatus.active
    notes: Optional[str] = None
    is_internal: bool = False
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    billing_cycle: Optional[BillingCycle] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[date] = None
    last_invoiced_date: Optional[date] = None
    # Revenue intelligence
    business_model: Optional[str] = None
    aov: Optional[float] = None
    conversion_rate: Optional[float] = None
    ltv: Optional[float] = None
    seo_maturity_level: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: Optional[ContractType] = None
    monthly_budget: Optional[float] = Field(None, ge=0)
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None
    is_internal: Optional[bool] = None
    ga4_property_id: Optional[str] = None
    gsc_url: Optional[str] = None
    billing_cycle: Optional[BillingCycle] = None
    billing_day: Optional[int] = None
    next_invoice_date: Optional[date] = None
    last_invoiced_date: Optional[date] = None
    engine_project_id: Optional[int] = None
    # Revenue intelligence
    business_model: Optional[str] = None
    aov: Optional[float] = None
    conversion_rate: Optional[float] = None
    ltv: Optional[float] = None
    seo_maturity_level: Optional[str] = None


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
    engine_content_count: Optional[int] = None
    engine_keyword_count: Optional[int] = None
    engine_avg_position: Optional[float] = None
    engine_clicks_30d: Optional[int] = None
    engine_impressions_30d: Optional[int] = None
    engine_metrics_synced_at: Optional[datetime] = None
    engine_summary_data: Optional[dict] = None
    engine_alerts_data: Optional[dict] = None
    # Revenue intelligence
    business_model: Optional[str] = None
    aov: Optional[float] = None
    conversion_rate: Optional[float] = None
    ltv: Optional[float] = None
    seo_maturity_level: Optional[str] = None
    is_internal: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
