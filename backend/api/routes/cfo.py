"""CFO module — delivery margin, utilization and P&L.

Cruces horas × cost_per_hour vs monthly_fee para saber la rentabilidad real
por proyecto, cliente y persona.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.db.database import get_db
from backend.db.models import User

router = APIRouter(prefix="/api/cfo", tags=["cfo"])


def _month_bounds(month: Optional[str]) -> tuple[date, date]:
    """Accept 'YYYY-MM' o devuelve el mes actual. Retorna (first_day, next_month_first_day)."""
    if month:
        y, m = map(int, month.split("-"))
    else:
        today = date.today()
        y, m = today.year, today.month
    first = date(y, m, 1)
    nxt = date(y + (m // 12), (m % 12) + 1, 1)
    return first, nxt


@router.get("/delivery-margin")
async def delivery_margin(
    month: Optional[str] = Query(None, description="YYYY-MM, mes actual por defecto"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Margen de delivery por proyecto del mes indicado."""
    first, nxt = _month_bounds(month)
    q = text("""
        SELECT
            p.id AS project_id,
            p.name AS project_name,
            c.id AS client_id,
            c.name AS client_name,
            COALESCE(p.monthly_fee, 0)::numeric AS monthly_fee,
            COALESCE(SUM(te.hours), 0)::numeric AS total_hours,
            COALESCE(SUM(te.hours * u.cost_per_hour), 0)::numeric AS labor_cost,
            (COALESCE(p.monthly_fee, 0) - COALESCE(SUM(te.hours * u.cost_per_hour), 0))::numeric AS delivery_margin,
            CASE
                WHEN COALESCE(SUM(te.hours), 0) > 0 THEN (p.monthly_fee / SUM(te.hours))::numeric
                ELSE NULL
            END AS abr,
            CASE
                WHEN COALESCE(p.monthly_fee, 0) > 0 THEN
                    ((p.monthly_fee - COALESCE(SUM(te.hours * u.cost_per_hour), 0)) / p.monthly_fee * 100)::numeric
                ELSE NULL
            END AS margin_pct
        FROM projects p
        JOIN clients c ON p.client_id = c.id
        LEFT JOIN time_entries te
          ON te.project_id = p.id
         AND te.date >= :first AND te.date < :nxt
        LEFT JOIN users u ON te.user_id = u.id
        WHERE COALESCE(p.monthly_fee, 0) > 0
        GROUP BY p.id, p.name, c.id, c.name, p.monthly_fee
        ORDER BY p.monthly_fee DESC
    """)
    rows = (await db.execute(q, {"first": first, "nxt": nxt})).mappings().all()
    return {
        "month": first.strftime("%Y-%m"),
        "projects": [
            {
                "project_id": r["project_id"],
                "project_name": r["project_name"],
                "client_id": r["client_id"],
                "client_name": r["client_name"],
                "monthly_fee": float(r["monthly_fee"]),
                "total_hours": float(r["total_hours"]),
                "labor_cost": float(r["labor_cost"]),
                "delivery_margin": float(r["delivery_margin"]),
                "abr": float(r["abr"]) if r["abr"] is not None else None,
                "margin_pct": float(r["margin_pct"]) if r["margin_pct"] is not None else None,
            }
            for r in rows
        ],
    }


@router.get("/utilization")
async def utilization(
    month: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Utilización por persona: billable vs internal vs disponible."""
    first, nxt = _month_bounds(month)
    q = text("""
        SELECT
            u.id AS user_id,
            u.full_name AS user_name,
            u.cost_per_hour::numeric AS cost_per_hour,
            u.available_hours_month::numeric AS available_hours_month,
            COALESCE(SUM(te.hours), 0)::numeric AS total_hours,
            COALESCE(SUM(CASE WHEN COALESCE(p.monthly_fee, 0) > 0 THEN te.hours ELSE 0 END), 0)::numeric AS billable_hours,
            COALESCE(SUM(CASE WHEN COALESCE(p.monthly_fee, 0) = 0 THEN te.hours ELSE 0 END), 0)::numeric AS internal_hours,
            CASE
                WHEN u.available_hours_month > 0 THEN
                    (COALESCE(SUM(CASE WHEN COALESCE(p.monthly_fee, 0) > 0 THEN te.hours ELSE 0 END), 0) / u.available_hours_month * 100)::numeric
                ELSE 0
            END AS utilization_pct
        FROM users u
        LEFT JOIN time_entries te
          ON te.user_id = u.id
         AND te.date >= :first AND te.date < :nxt
        LEFT JOIN projects p ON te.project_id = p.id
        WHERE u.is_active = TRUE
        GROUP BY u.id, u.full_name, u.cost_per_hour, u.available_hours_month
        ORDER BY u.full_name
    """)
    rows = (await db.execute(q, {"first": first, "nxt": nxt})).mappings().all()
    return {
        "month": first.strftime("%Y-%m"),
        "users": [
            {
                "user_id": r["user_id"],
                "user_name": r["user_name"],
                "cost_per_hour": float(r["cost_per_hour"]),
                "available_hours_month": float(r["available_hours_month"]),
                "total_hours": float(r["total_hours"]),
                "billable_hours": float(r["billable_hours"]),
                "internal_hours": float(r["internal_hours"]),
                "utilization_pct": float(r["utilization_pct"]),
            }
            for r in rows
        ],
    }


@router.get("/monthly-pl")
async def monthly_pl(
    month: Optional[str] = Query(None),
    overhead: float = Query(1585.00, description="Overhead fijo mensual"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """P&L simplificado del mes: revenue − labor cost − overhead."""
    first, nxt = _month_bounds(month)

    rev_q = text("""
        SELECT COALESCE(SUM(monthly_fee), 0)::numeric AS revenue
        FROM projects
        WHERE COALESCE(monthly_fee, 0) > 0 AND status = 'active'
    """)
    cost_q = text("""
        SELECT COALESCE(SUM(te.hours * u.cost_per_hour), 0)::numeric AS labor_cost
        FROM time_entries te
        JOIN users u ON te.user_id = u.id
        WHERE te.date >= :first AND te.date < :nxt
    """)
    revenue = float((await db.execute(rev_q)).scalar() or 0)
    labor_cost = float((await db.execute(cost_q, {"first": first, "nxt": nxt})).scalar() or 0)
    delivery_margin = revenue - labor_cost
    net = delivery_margin - overhead
    return {
        "month": first.strftime("%Y-%m"),
        "revenue": revenue,
        "labor_cost": labor_cost,
        "delivery_margin": delivery_margin,
        "overhead": overhead,
        "net_before_tax": net,
    }


@router.get("/alerts")
async def alerts(
    month: Optional[str] = Query(None),
    abr_threshold: float = Query(30.0),
    utilization_low: float = Query(60.0),
    utilization_high: float = Query(90.0),
    concentration_threshold: float = Query(40.0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Alertas automáticas basadas en los cruces delivery margin + utilización."""
    alerts_list: list[dict] = []

    # Delivery margin por proyecto
    margin = await delivery_margin(month=month, db=db, _=None)  # type: ignore
    total_revenue = 0.0
    revenue_by_client: dict[int, tuple[str, float]] = {}
    for p in margin["projects"]:
        total_revenue += p["monthly_fee"]
        name, acc = revenue_by_client.get(p["client_id"], (p["client_name"], 0.0))
        revenue_by_client[p["client_id"]] = (name, acc + p["monthly_fee"])
        if p["delivery_margin"] < 0:
            alerts_list.append({
                "severity": "critical",
                "type": "negative_margin",
                "message": f"{p['project_name']} ({p['client_name']}): margen {p['delivery_margin']:.2f} €",
                "project_id": p["project_id"],
            })
        if p["abr"] is not None and p["abr"] < abr_threshold:
            alerts_list.append({
                "severity": "critical",
                "type": "low_abr",
                "message": f"{p['project_name']}: ABR {p['abr']:.1f}€/h < {abr_threshold}€/h",
                "project_id": p["project_id"],
            })

    # Concentración por cliente
    for cid, (cname, rev) in revenue_by_client.items():
        if total_revenue > 0 and (rev / total_revenue * 100) > concentration_threshold:
            alerts_list.append({
                "severity": "high",
                "type": "client_concentration",
                "message": f"{cname}: {rev / total_revenue * 100:.1f}% del revenue total",
                "client_id": cid,
            })

    # Utilización
    util = await utilization(month=month, db=db, _=None)  # type: ignore
    for u in util["users"]:
        pct = u["utilization_pct"]
        if pct > 0 and pct < utilization_low:
            alerts_list.append({
                "severity": "medium",
                "type": "low_utilization",
                "message": f"{u['user_name']}: {pct:.0f}% utilización",
                "user_id": u["user_id"],
            })
        elif pct > utilization_high:
            alerts_list.append({
                "severity": "medium",
                "type": "high_utilization",
                "message": f"{u['user_name']}: {pct:.0f}% utilización",
                "user_id": u["user_id"],
            })

    return {"month": margin["month"], "alerts": alerts_list}
