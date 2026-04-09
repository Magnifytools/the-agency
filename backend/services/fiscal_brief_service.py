"""Fiscal brief service — collects financial data and generates AI-powered quarterly reports."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Income, Expense, Tax, Client, BalanceSnapshot,
    HoldedInvoiceCache, AdvisorAiBrief, AdvisorAiBriefPayload,
    Forecast, ExpenseCategory,
)
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)

QUARTER_RANGES = {
    "Q1": (1, 3),
    "Q2": (4, 6),
    "Q3": (7, 9),
    "Q4": (10, 12),
}


def _quarter_dates(year: int, quarter: str) -> tuple[date, date]:
    """Return (start_date, end_date) for a quarter."""
    start_month, end_month = QUARTER_RANGES[quarter]
    start = date(year, start_month, 1)
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


async def collect_fiscal_data(
    db: AsyncSession,
    year: int,
    quarter: str,
) -> dict:
    """Collect all financial data for a quarter to feed the AI brief."""
    start, end = _quarter_dates(year, quarter)
    prev_year = year - 1 if quarter == "Q1" else year
    prev_quarter = {"Q1": "Q4", "Q2": "Q1", "Q3": "Q2", "Q4": "Q3"}[quarter]
    prev_start, prev_end = _quarter_dates(prev_year, prev_quarter)

    # ── Income by client ──
    income_result = await db.execute(
        select(
            Client.name,
            func.sum(Income.amount).label("total"),
            func.count(Income.id).label("count"),
            func.sum(case((Income.status == "pendiente", Income.amount), else_=0)).label("pending"),
        )
        .outerjoin(Client, Income.client_id == Client.id)
        .where(Income.date >= start, Income.date <= end)
        .group_by(Client.name)
    )
    income_by_client = [
        {"client": r[0] or "Sin cliente", "total": float(r[1] or 0), "count": r[2], "pending": float(r[3] or 0)}
        for r in income_result.all()
    ]
    total_income = sum(r["total"] for r in income_by_client)
    total_pending = sum(r["pending"] for r in income_by_client)

    # ── Previous quarter income (for comparison) ──
    prev_income_result = await db.execute(
        select(func.sum(Income.amount))
        .where(Income.date >= prev_start, Income.date <= prev_end)
    )
    prev_total_income = float(prev_income_result.scalar() or 0)

    # ── Expenses by category ──
    expense_result = await db.execute(
        select(
            ExpenseCategory.name,
            func.sum(Expense.amount).label("total"),
            func.count(Expense.id).label("count"),
        )
        .outerjoin(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
        .where(Expense.date >= start, Expense.date <= end)
        .group_by(ExpenseCategory.name)
    )
    expenses_by_category = [
        {"category": r[0] or "Sin categoría", "total": float(r[1] or 0), "count": r[2]}
        for r in expense_result.all()
    ]
    total_expenses = sum(r["total"] for r in expenses_by_category)

    # ── Previous quarter expenses ──
    prev_expense_result = await db.execute(
        select(func.sum(Expense.amount))
        .where(Expense.date >= prev_start, Expense.date <= prev_end)
    )
    prev_total_expenses = float(prev_expense_result.scalar() or 0)

    # ── Taxes ──
    taxes_result = await db.execute(
        select(Tax).where(
            Tax.year == year,
            Tax.period == quarter,
        )
    )
    taxes = [
        {
            "model": t.model,
            "name": t.name,
            "amount": float(t.tax_amount or 0),
            "status": t.status,
            "due_date": t.due_date.isoformat() if t.due_date else None,
        }
        for t in taxes_result.scalars().all()
    ]
    total_taxes = sum(t["amount"] for t in taxes if t["status"] == "pendiente")

    # ── Pending invoices (from Holded cache or Income) ──
    pending_invoices = await db.execute(
        select(Income)
        .outerjoin(Client, Income.client_id == Client.id)
        .where(Income.status == "pendiente")
        .order_by(Income.date.asc())
    )
    pending_list = []
    for inv in pending_invoices.scalars().all():
        days_old = (date.today() - inv.date).days if inv.date else 0
        pending_list.append({
            "client": inv.client.name if inv.client else "Sin cliente",
            "amount": float(inv.amount or 0),
            "date": inv.date.isoformat() if inv.date else "",
            "days_pending": days_old,
            "invoice_number": inv.invoice_number or "",
        })

    # ── Active clients + monthly fees ──
    clients_result = await db.execute(
        select(Client.name, Client.monthly_budget, Client.contract_type)
        .where(Client.status == "active")
    )
    active_clients = [
        {"name": r[0], "monthly_fee": float(r[1] or 0), "contract_type": r[2]}
        for r in clients_result.all()
    ]

    # ── Balance ──
    balance_result = await db.execute(
        select(BalanceSnapshot).order_by(BalanceSnapshot.date.desc()).limit(1)
    )
    balance = balance_result.scalar_one_or_none()
    cash = float(balance.amount) if balance else None

    # ── Tax regime notes (specific client issues) ──
    # Check for clients with non-standard tax regime invoices
    special_regime = await db.execute(
        select(Client.name, Income.tax_regime, func.count(Income.id))
        .outerjoin(Client, Income.client_id == Client.id)
        .where(
            Income.date >= start,
            Income.date <= end,
            Income.tax_regime != "standard",
            Income.tax_regime.isnot(None),
        )
        .group_by(Client.name, Income.tax_regime)
    )
    tax_regime_notes = [
        {"client": r[0] or "?", "regime": r[1], "count": r[2]}
        for r in special_regime.all()
    ]

    profit = total_income - total_expenses
    prev_profit = prev_total_income - prev_total_expenses
    margin = (profit / total_income * 100) if total_income else 0

    return {
        "year": year,
        "quarter": quarter,
        "period": f"{start.isoformat()} al {end.isoformat()}",
        "summary": {
            "total_income": total_income,
            "total_expenses": total_expenses,
            "profit": profit,
            "margin_pct": round(margin, 1),
            "total_pending_invoices": total_pending,
            "total_pending_taxes": total_taxes,
            "cash_balance": cash,
        },
        "comparison": {
            "prev_quarter": prev_quarter,
            "prev_income": prev_total_income,
            "prev_expenses": prev_total_expenses,
            "prev_profit": prev_profit,
            "income_change_pct": round((total_income - prev_total_income) / prev_total_income * 100, 1) if prev_total_income else None,
        },
        "income_by_client": income_by_client,
        "expenses_by_category": expenses_by_category,
        "taxes": taxes,
        "pending_invoices": pending_list,
        "active_clients": active_clients,
        "tax_regime_notes": tax_regime_notes,
    }


BRIEF_SYSTEM_PROMPT = """\
Eres el asesor fiscal interno de Magnify, una agencia de marketing digital en España.
Tu trabajo es generar informes trimestrales claros y accionables para el CEO (David).

REGLAS:
1. Escribe en español, tono profesional pero directo (tutea a David).
2. Usa datos reales — NO inventes cifras. Si un dato no está, dilo.
3. Sé específico: nombres de clientes, importes exactos, fechas.
4. Destaca alertas y acciones concretas que David debe tomar.
5. Compara con el trimestre anterior cuando sea relevante.
6. Para impuestos, menciona los modelos específicos (303, 111, 200).
7. Si hay clientes con régimen fiscal especial (no sujeto, intracomunitario), alerta.
8. El informe debe ser completo pero conciso — que se pueda leer en 2 minutos.
9. Responde en JSON con la estructura indicada.
"""

BRIEF_USER_PROMPT = """\
Genera el informe fiscal del {quarter} {year} con estos datos:

RESUMEN:
- Ingresos: {total_income:.2f}€
- Gastos: {total_expenses:.2f}€
- Beneficio: {profit:.2f}€ (margen {margin_pct}%)
- Facturas pendientes de cobro: {total_pending_invoices:.2f}€
- Impuestos pendientes: {total_pending_taxes:.2f}€
- Saldo en cuenta: {cash_balance}

COMPARATIVA VS {prev_quarter}:
- Ingresos anterior: {prev_income:.2f}€ (cambio: {income_change_pct}%)
- Gastos anterior: {prev_expenses:.2f}€
- Beneficio anterior: {prev_profit:.2f}€

INGRESOS POR CLIENTE:
{income_by_client_text}

GASTOS POR CATEGORÍA:
{expenses_by_category_text}

IMPUESTOS DEL TRIMESTRE:
{taxes_text}

FACTURAS PENDIENTES DE COBRO:
{pending_invoices_text}

CLIENTES ACTIVOS:
{active_clients_text}

RÉGIMEN FISCAL ESPECIAL:
{tax_regime_text}

Responde con este JSON:
{{
  "title": "Informe fiscal {quarter} {year}",
  "executive_summary": "Párrafo resumen de 3-4 líneas con lo más importante",
  "income_analysis": "Análisis de ingresos por cliente, tendencias",
  "expense_analysis": "Análisis de gastos, partidas relevantes",
  "tax_status": "Estado de cada modelo fiscal, importes a pagar, fechas",
  "alerts": ["Alerta 1 con acción concreta", "Alerta 2..."],
  "pending_actions": ["Acción 1", "Acción 2..."],
  "recommendations": ["Recomendación 1", "Recomendación 2..."]
}}"""


def _format_list(items: list[dict], fmt: str) -> str:
    """Format a list of dicts as bullet points."""
    if not items:
        return "(ninguno)"
    return "\n".join(fmt.format(**item) for item in items)


async def generate_fiscal_brief(
    db: AsyncSession,
    year: int,
    quarter: str,
) -> AdvisorAiBrief:
    """Generate an AI-powered fiscal brief for a quarter."""
    data = await collect_fiscal_data(db, year, quarter)
    summary = data["summary"]
    comp = data["comparison"]

    user_prompt = BRIEF_USER_PROMPT.format(
        quarter=quarter,
        year=year,
        total_income=summary["total_income"],
        total_expenses=summary["total_expenses"],
        profit=summary["profit"],
        margin_pct=summary["margin_pct"],
        total_pending_invoices=summary["total_pending_invoices"],
        total_pending_taxes=summary["total_pending_taxes"],
        cash_balance=f"{summary['cash_balance']:.2f}€" if summary["cash_balance"] is not None else "No disponible",
        prev_quarter=comp["prev_quarter"],
        prev_income=comp["prev_income"],
        prev_expenses=comp["prev_expenses"],
        prev_profit=comp["prev_profit"],
        income_change_pct=f"{comp['income_change_pct']}%" if comp["income_change_pct"] is not None else "N/A",
        income_by_client_text=_format_list(
            data["income_by_client"],
            "- {client}: {total:.2f}€ ({count} facturas, pendiente: {pending:.2f}€)"
        ),
        expenses_by_category_text=_format_list(
            data["expenses_by_category"],
            "- {category}: {total:.2f}€ ({count} registros)"
        ),
        taxes_text=_format_list(
            data["taxes"],
            "- Modelo {model} ({name}): {amount:.2f}€ — {status} (vence: {due_date})"
        ),
        pending_invoices_text=_format_list(
            data["pending_invoices"],
            "- {client}: {amount:.2f}€ (factura {invoice_number}, emitida {date}, {days_pending} días pendiente)"
        ),
        active_clients_text=_format_list(
            data["active_clients"],
            "- {name}: {monthly_fee:.2f}€/mes ({contract_type})"
        ),
        tax_regime_text=_format_list(
            data["tax_regime_notes"],
            "- {client}: régimen '{regime}' ({count} facturas)"
        ) if data["tax_regime_notes"] else "Todo estándar, sin regímenes especiales.",
    )

    client = get_anthropic_client()
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=BRIEF_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = parse_claude_json(message)

    # Store in DB
    brief = AdvisorAiBrief(
        period_start=_quarter_dates(year, quarter)[0],
        period_end=_quarter_dates(year, quarter)[1],
        content=str(content) if isinstance(content, dict) else content,
        model="claude-sonnet-4-20250514",
        provider="anthropic",
    )
    db.add(brief)

    # Store raw data as payload
    import json
    payload = AdvisorAiBriefPayload(
        brief=brief,
        payload=json.dumps(data, default=str, ensure_ascii=False),
    )
    db.add(payload)

    await db.commit()
    await db.refresh(brief)

    logger.info("Fiscal brief generated for %s %d (id=%d)", quarter, year, brief.id)
    return brief, content
