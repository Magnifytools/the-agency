from __future__ import annotations
from typing import Optional
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel
from backend.db.models import LeadStatus, LeadSource, LeadActivityType


class LeadCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: LeadStatus = LeadStatus.new
    source: LeadSource = LeadSource.other
    assigned_to: Optional[int] = None
    estimated_value: Optional[Decimal] = None
    service_interest: Optional[str] = None
    currency: str = "EUR"
    notes: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    current_website_traffic: Optional[str] = None
    next_followup_date: Optional[date] = None
    next_followup_notes: Optional[str] = None


class LeadUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: Optional[LeadStatus] = None
    source: Optional[LeadSource] = None
    assigned_to: Optional[int] = None
    estimated_value: Optional[Decimal] = None
    service_interest: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    current_website_traffic: Optional[str] = None
    next_followup_date: Optional[date] = None
    next_followup_notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    lost_reason: Optional[str] = None


class LeadResponse(BaseModel):
    id: int
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: LeadStatus
    source: LeadSource
    assigned_to: Optional[int] = None
    assigned_user_name: Optional[str] = None
    estimated_value: Optional[Decimal] = None
    service_interest: Optional[str] = None
    currency: str = "EUR"
    notes: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    current_website_traffic: Optional[str] = None
    next_followup_date: Optional[date] = None
    next_followup_notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    converted_client_id: Optional[int] = None
    converted_at: Optional[datetime] = None
    lost_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadActivityCreate(BaseModel):
    activity_type: LeadActivityType
    title: str
    description: Optional[str] = None


class LeadActivityResponse(BaseModel):
    id: int
    lead_id: int
    user_id: int
    user_name: Optional[str] = None
    activity_type: LeadActivityType
    title: str
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadDetailResponse(LeadResponse):
    activities: list[LeadActivityResponse] = []


class PipelineStageSummary(BaseModel):
    status: LeadStatus
    count: int
    total_value: Decimal = Decimal("0")


class PipelineSummary(BaseModel):
    stages: list[PipelineStageSummary]
    total_leads: int
    total_value: Decimal = Decimal("0")


class LeadReminderResponse(BaseModel):
    id: int
    company_name: str
    contact_name: Optional[str] = None
    next_followup_date: Optional[date] = None
    next_followup_notes: Optional[str] = None
    status: LeadStatus
    assigned_user_name: Optional[str] = None
    days_until_followup: int = 0
