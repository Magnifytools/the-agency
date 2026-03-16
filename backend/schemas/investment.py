from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class InvestmentCalculateRequest(BaseModel):
    client_id: Optional[int] = None
    proposal_id: Optional[int] = None
    # Manual overrides (used when client data is missing or user wants custom values)
    business_model: Optional[str] = None
    aov: Optional[float] = None
    conversion_rate: Optional[float] = None
    ltv: Optional[float] = None
    seo_maturity: Optional[str] = None
    current_monthly_traffic: Optional[int] = None
    monthly_investment: Optional[float] = None
    months: int = 12


class InvestmentScenario(BaseModel):
    label: str
    key: str
    traffic_increase: int
    new_conversions: float
    revenue_increase: float
    roi_percent: float
    payback_months: Optional[int] = None


class InvestmentMonthlyRow(BaseModel):
    month: int
    traffic: int
    new_visitors: int
    conversions: float
    revenue: float
    cumulative_investment: float
    cumulative_revenue: float
    roi: float


class InvestmentSummary(BaseModel):
    break_even_month: Optional[int] = None
    year1_roi_range: str
    year1_revenue_range: str
    total_investment: float
    opportunity_cost: Optional[float] = None


class InvestmentAssumptions(BaseModel):
    seo_maturity: str
    base_growth_rate: str
    ramp_up_months: int
    ltv_factor: float
    conversion_rate: float


class NullScenarioMonthlyRow(BaseModel):
    month: int
    traffic: int
    lost_visitors: int
    lost_conversions: float
    lost_revenue: float
    cumulative_opportunity_cost: float


class NullScenario(BaseModel):
    label: str
    traffic_decline: int
    lost_conversions: float
    lost_revenue: float
    cumulative_opportunity_cost: float
    monthly_projection: list[NullScenarioMonthlyRow]


class PricingTierRoi(BaseModel):
    name: str
    price: float
    is_recommended: bool
    roi_conservative: float
    roi_moderate: float
    roi_optimistic: float
    payback_months: Optional[int] = None


class InvestmentCalculateResponse(BaseModel):
    scenarios: list[InvestmentScenario]
    null_scenario: Optional[NullScenario] = None
    pricing_comparison: Optional[list[PricingTierRoi]] = None
    monthly_projection: list[InvestmentMonthlyRow]
    summary: InvestmentSummary
    assumptions: InvestmentAssumptions
    inputs_used: dict
