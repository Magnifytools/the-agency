from __future__ import annotations
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field, ConfigDict

from backend.db.models import ProposalStatus, ServiceType


# ── Pricing Option ─────────────────────────────────────────

class PricingOption(BaseModel):
    name: str
    description: str = ""
    ideal_for: str = ""
    price: float
    is_recurring: bool = False
    recommended: bool = False


# ── Service Template schemas ───────────────────────────────

class PhaseItem(BaseModel):
    name: str
    duration: str
    outcome: str


class ServiceTemplateResponse(BaseModel):
    id: int
    service_type: ServiceType
    name: str
    description: Optional[str] = None
    is_recurring: bool
    price_range_min: Optional[float] = None
    price_range_max: Optional[float] = None
    default_phases: Optional[list[PhaseItem]] = None
    default_includes: Optional[str] = None
    default_excludes: Optional[str] = None
    prompt_context: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_recurring: Optional[bool] = None
    price_range_min: Optional[float] = None
    price_range_max: Optional[float] = None
    default_phases: Optional[list[PhaseItem]] = None
    default_includes: Optional[str] = None
    default_excludes: Optional[str] = None
    prompt_context: Optional[str] = None


# ── Proposal schemas ───────────────────────────────────────

class ProposalCreate(BaseModel):
    title: str = Field(..., max_length=300)
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    contact_name: Optional[str] = None
    company_name: str = ""
    service_type: Optional[ServiceType] = None

    # Contexto
    situation: Optional[str] = None
    problem: Optional[str] = None
    cost_of_inaction: Optional[str] = None
    opportunity: Optional[str] = None
    approach: Optional[str] = None
    relevant_cases: Optional[str] = None

    # Pricing
    pricing_options: Optional[list[PricingOption]] = None

    # Internal
    internal_hours_david: Optional[float] = None
    internal_hours_nacho: Optional[float] = None
    internal_cost_estimate: Optional[float] = None
    estimated_margin_percent: Optional[float] = None

    # Content
    generated_content: Optional[dict] = None

    valid_until: Optional[date] = None


class ProposalUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=300)
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    contact_name: Optional[str] = None
    company_name: Optional[str] = None
    service_type: Optional[ServiceType] = None

    situation: Optional[str] = None
    problem: Optional[str] = None
    cost_of_inaction: Optional[str] = None
    opportunity: Optional[str] = None
    approach: Optional[str] = None
    relevant_cases: Optional[str] = None

    pricing_options: Optional[list[PricingOption]] = None

    internal_hours_david: Optional[float] = None
    internal_hours_nacho: Optional[float] = None
    internal_cost_estimate: Optional[float] = None
    estimated_margin_percent: Optional[float] = None

    generated_content: Optional[dict] = None

    valid_until: Optional[date] = None
    status: Optional[ProposalStatus] = None
    response_notes: Optional[str] = None


class ProposalStatusUpdate(BaseModel):
    status: ProposalStatus
    response_notes: Optional[str] = None


class ProposalResponse(BaseModel):
    id: int
    title: str
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    created_by: Optional[int] = None
    contact_name: Optional[str] = None
    company_name: str = ""
    service_type: Optional[ServiceType] = None

    situation: Optional[str] = None
    problem: Optional[str] = None
    cost_of_inaction: Optional[str] = None
    opportunity: Optional[str] = None
    approach: Optional[str] = None
    relevant_cases: Optional[str] = None

    pricing_options: Optional[list[PricingOption]] = None

    internal_hours_david: Optional[float] = None
    internal_hours_nacho: Optional[float] = None
    internal_cost_estimate: Optional[float] = None
    estimated_margin_percent: Optional[float] = None

    generated_content: Optional[dict] = None

    status: ProposalStatus
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    response_notes: Optional[str] = None
    valid_until: Optional[date] = None

    converted_project_id: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    # Denormalized
    client_name: Optional[str] = None
    lead_company: Optional[str] = None
    created_by_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
