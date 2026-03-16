"""Stateless SEO ROI calculator.

Pure calculation — no DB access. Called by the investments API route
which handles loading client/proposal data.
"""
from __future__ import annotations


# Growth rates by SEO maturity (monthly, conservative scenario)
_GROWTH_RATES = {
    "none": 0.15,
    "basic": 0.25,
    "intermediate": 0.35,
    "advanced": 0.20,
}

_RAMP_UP_MONTHS = 3  # SEO takes ~3 months to show results


def calculate_seo_roi(
    business_model: str,
    aov: float,
    conversion_rate: float,
    ltv: float,
    current_monthly_traffic: int,
    monthly_investment: float,
    seo_maturity: str = "none",
    months: int = 12,
) -> dict:
    """Calculate SEO ROI across 3 scenarios with monthly projections.

    Args:
        business_model: ecommerce, saas, lead_gen, media
        aov: Average order value in EUR
        conversion_rate: Conversion rate 0-100
        ltv: Customer lifetime value in EUR
        current_monthly_traffic: Current monthly organic visitors
        monthly_investment: Monthly SEO investment in EUR
        seo_maturity: none, basic, intermediate, advanced
        months: Projection horizon (default 12)

    Returns:
        Dict with scenarios, monthly_projection, summary, and assumptions.
    """
    conv_rate = conversion_rate / 100.0
    base_growth = _GROWTH_RATES.get(seo_maturity, 0.15)

    # LTV factor: for recurring businesses, value compounds
    ltv_factor = ltv / aov if aov > 0 and ltv > aov else 1.0

    # Scenario multipliers relative to conservative
    scenario_configs = [
        {"label": "Conservador", "key": "conservative", "multiplier": 1.0},
        {"label": "Moderado", "key": "moderate", "multiplier": 1.5},
        {"label": "Optimista", "key": "optimistic", "multiplier": 2.2},
    ]

    # Null scenario: what happens if the client does NOT invest
    null_monthly = []
    null_cumulative_cost = 0.0
    # Organic decay: without SEO investment, traffic typically declines 2-5% monthly
    _ORGANIC_DECAY = 0.02
    for m in range(1, months + 1):
        decay_traffic = int(current_monthly_traffic * (1 - _ORGANIC_DECAY) ** m)
        lost_visitors = current_monthly_traffic - decay_traffic
        lost_conversions = lost_visitors * conv_rate
        lost_revenue = lost_conversions * aov * ltv_factor
        null_cumulative_cost += lost_revenue
        null_monthly.append({
            "month": m,
            "traffic": decay_traffic,
            "lost_visitors": lost_visitors,
            "lost_conversions": round(lost_conversions, 1),
            "lost_revenue": round(lost_revenue, 2),
            "cumulative_opportunity_cost": round(null_cumulative_cost, 2),
        })

    total_investment = monthly_investment * months
    scenarios = []
    all_monthly = {}

    for sc in scenario_configs:
        growth = base_growth * sc["multiplier"]
        monthly_rows = []
        cumulative_investment = 0.0
        cumulative_revenue = 0.0

        for m in range(1, months + 1):
            cumulative_investment += monthly_investment

            # Ramp-up: no growth in first N months
            if m <= _RAMP_UP_MONTHS:
                traffic = current_monthly_traffic
                new_visitors = 0
            else:
                effective_months = m - _RAMP_UP_MONTHS
                # Compounding growth
                traffic = int(current_monthly_traffic * (1 + growth) ** effective_months)
                new_visitors = traffic - current_monthly_traffic

            new_conversions = new_visitors * conv_rate
            month_revenue = new_conversions * aov * ltv_factor
            cumulative_revenue += month_revenue
            roi = ((cumulative_revenue - cumulative_investment) / cumulative_investment * 100) if cumulative_investment > 0 else 0

            monthly_rows.append({
                "month": m,
                "traffic": traffic,
                "new_visitors": new_visitors,
                "conversions": round(new_conversions, 1),
                "revenue": round(month_revenue, 2),
                "cumulative_investment": round(cumulative_investment, 2),
                "cumulative_revenue": round(cumulative_revenue, 2),
                "roi": round(roi, 1),
            })

        all_monthly[sc["key"]] = monthly_rows

        # Final month values for scenario summary
        final = monthly_rows[-1]
        scenarios.append({
            "label": sc["label"],
            "key": sc["key"],
            "traffic_increase": final["new_visitors"],
            "new_conversions": round(final["conversions"], 1),
            "revenue_increase": round(final["revenue"], 2),
            "roi_percent": round(final["roi"], 1),
            "payback_months": _find_payback_month(monthly_rows),
        })

    # Summary across scenarios
    conservative_payback = scenarios[0]["payback_months"]
    optimistic_payback = scenarios[2]["payback_months"]
    break_even = conservative_payback or optimistic_payback

    year1_roi_low = scenarios[0]["roi_percent"]
    year1_roi_high = scenarios[2]["roi_percent"]

    year1_rev_low = round(all_monthly["conservative"][-1]["cumulative_revenue"], 0)
    year1_rev_high = round(all_monthly["optimistic"][-1]["cumulative_revenue"], 0)

    null_final = null_monthly[-1]

    return {
        "scenarios": scenarios,
        "null_scenario": {
            "label": "Sin inversión",
            "traffic_decline": null_final["lost_visitors"],
            "lost_conversions": null_final["lost_conversions"],
            "lost_revenue": null_final["lost_revenue"],
            "cumulative_opportunity_cost": null_final["cumulative_opportunity_cost"],
            "monthly_projection": null_monthly,
        },
        "monthly_projection": all_monthly["moderate"],  # Show moderate by default
        "summary": {
            "break_even_month": break_even,
            "year1_roi_range": f"{year1_roi_low}% – {year1_roi_high}%",
            "year1_revenue_range": f"{year1_rev_low:,.0f}€ – {year1_rev_high:,.0f}€",
            "total_investment": round(total_investment, 2),
            "opportunity_cost": null_final["cumulative_opportunity_cost"],
        },
        "assumptions": {
            "seo_maturity": seo_maturity,
            "base_growth_rate": f"{base_growth * 100:.0f}%",
            "ramp_up_months": _RAMP_UP_MONTHS,
            "ltv_factor": round(ltv_factor, 2),
            "conversion_rate": conversion_rate,
        },
    }


def _find_payback_month(rows: list[dict]) -> int | None:
    """Find first month where cumulative revenue exceeds cumulative investment."""
    for row in rows:
        if row["cumulative_revenue"] >= row["cumulative_investment"] and row["cumulative_revenue"] > 0:
            return row["month"]
    return None
