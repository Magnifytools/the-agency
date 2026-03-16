from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Client, Proposal, User
from backend.api.deps import require_module
from backend.core.rate_limiter import ai_limiter
from backend.schemas.investment import InvestmentCalculateRequest, InvestmentCalculateResponse
from backend.services.investment_calculator import calculate_seo_roi

router = APIRouter(prefix="/api/investments", tags=["investments"])
logger = logging.getLogger(__name__)


@router.post("/calculate", response_model=InvestmentCalculateResponse)
async def calculate_investment(
    body: InvestmentCalculateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("proposals")),
):
    """Calculate SEO ROI model. Auto-fills from client/proposal when available."""
    ai_limiter.check(current_user.id, max_requests=30, window_seconds=300)

    # Collect inputs — manual overrides take priority
    business_model = body.business_model
    aov = body.aov
    conversion_rate = body.conversion_rate
    ltv = body.ltv
    seo_maturity = body.seo_maturity
    current_monthly_traffic = body.current_monthly_traffic
    monthly_investment = body.monthly_investment

    # Auto-fill from client
    if body.client_id:
        result = await db.execute(select(Client).where(Client.id == body.client_id))
        client = result.scalar_one_or_none()
        if client:
            if not business_model and client.business_model:
                business_model = client.business_model
            if aov is None and client.aov is not None:
                aov = client.aov
            if conversion_rate is None and client.conversion_rate is not None:
                conversion_rate = client.conversion_rate
            if ltv is None and client.ltv is not None:
                ltv = client.ltv
            if not seo_maturity and client.seo_maturity_level:
                seo_maturity = client.seo_maturity_level

    # Auto-fill monthly_investment from proposal's recommended pricing
    if body.proposal_id and monthly_investment is None:
        result = await db.execute(select(Proposal).where(Proposal.id == body.proposal_id))
        proposal = result.scalar_one_or_none()
        if proposal and proposal.pricing_options:
            for opt in proposal.pricing_options:
                if isinstance(opt, dict) and opt.get("recommended") and opt.get("is_recurring"):
                    monthly_investment = opt.get("price")
                    break
            # Fallback to first recurring option
            if monthly_investment is None:
                for opt in proposal.pricing_options:
                    if isinstance(opt, dict) and opt.get("is_recurring"):
                        monthly_investment = opt.get("price")
                        break

    # Validate required fields
    missing = []
    if not business_model:
        missing.append("business_model")
    if aov is None:
        missing.append("aov")
    if conversion_rate is None:
        missing.append("conversion_rate")
    if ltv is None:
        missing.append("ltv")
    if current_monthly_traffic is None:
        missing.append("current_monthly_traffic")
    if monthly_investment is None:
        missing.append("monthly_investment")

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Faltan campos requeridos: {', '.join(missing)}. Completa los datos del cliente o proporcionalos manualmente.",
        )

    result = calculate_seo_roi(
        business_model=business_model,
        aov=aov,
        conversion_rate=conversion_rate,
        ltv=ltv,
        current_monthly_traffic=current_monthly_traffic,
        monthly_investment=monthly_investment,
        seo_maturity=seo_maturity or "none",
        months=body.months,
    )

    # Calculate ROI for each pricing tier if proposal has multiple options
    pricing_comparison = None
    if body.proposal_id:
        res = await db.execute(select(Proposal).where(Proposal.id == body.proposal_id))
        prop = res.scalar_one_or_none()
        if prop and prop.pricing_options and len(prop.pricing_options) > 1:
            tiers = []
            for opt in prop.pricing_options:
                if not isinstance(opt, dict) or not opt.get("is_recurring") or not opt.get("price"):
                    continue
                tier_result = calculate_seo_roi(
                    business_model=business_model,
                    aov=aov,
                    conversion_rate=conversion_rate,
                    ltv=ltv,
                    current_monthly_traffic=current_monthly_traffic,
                    monthly_investment=opt["price"],
                    seo_maturity=seo_maturity or "none",
                    months=body.months,
                )
                scenarios_by_key = {s["key"]: s for s in tier_result["scenarios"]}
                tiers.append({
                    "name": opt.get("name", "Sin nombre"),
                    "price": opt["price"],
                    "is_recommended": bool(opt.get("recommended")),
                    "roi_conservative": scenarios_by_key["conservative"]["roi_percent"],
                    "roi_moderate": scenarios_by_key["moderate"]["roi_percent"],
                    "roi_optimistic": scenarios_by_key["optimistic"]["roi_percent"],
                    "payback_months": scenarios_by_key["conservative"]["payback_months"],
                })
            if tiers:
                pricing_comparison = tiers

    return InvestmentCalculateResponse(
        scenarios=result["scenarios"],
        null_scenario=result.get("null_scenario"),
        pricing_comparison=pricing_comparison,
        monthly_projection=result["monthly_projection"],
        summary=result["summary"],
        assumptions=result["assumptions"],
        inputs_used={
            "business_model": business_model,
            "aov": aov,
            "conversion_rate": conversion_rate,
            "ltv": ltv,
            "current_monthly_traffic": current_monthly_traffic,
            "monthly_investment": monthly_investment,
            "seo_maturity": seo_maturity or "none",
            "months": body.months,
        },
    )
