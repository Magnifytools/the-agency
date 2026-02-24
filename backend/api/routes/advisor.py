from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, extract, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Income, Expense, Tax, FinancialInsight, AdvisorTask,
    AdvisorAiBrief, AdvisorAiBriefPayload, FinancialSettings,
    MonthlyClose, User,
)
from backend.schemas.advisor import (
    FinancialInsightResponse, AdvisorTaskCreate, AdvisorTaskResponse,
    AdvisorAiBriefResponse, AdvisorOverview,
)
from backend.schemas.dashboard import MonthlyCloseResponse, MonthlyCloseUpdate
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/advisor", tags=["finance-advisor"])


# --- Helpers ---

def _month_range(year: int, month: int):
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, last_day)
    return start, end


async def _sum_income_month(db: AsyncSession, year: int, month: int) -> float:
    start, end = _month_range(year, month)
    r = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.date >= start, Income.date <= end)
    )
    return float(r.scalar())


async def _sum_expenses_month(db: AsyncSession, year: int, month: int) -> float:
    start, end = _month_range(year, month)
    r = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.date >= start, Expense.date <= end)
    )
    return float(r.scalar())


async def _build_insights(db: AsyncSession) -> list[dict]:
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    income = await _sum_income_month(db, y, m)
    expenses = await _sum_expenses_month(db, y, m)
    profit = income - expenses
    insights = []

    if profit < 0:
        insights.append({
            "type": "alerta",
            "title": "Cashflow negativo este mes",
            "description": f"Ingresos: {income:.2f}€, Gastos: {expenses:.2f}€. Resultado: {profit:.2f}€",
            "severity": "critical",
        })

    # Pending taxes
    r = await db.execute(
        select(func.coalesce(func.sum(Tax.tax_amount), 0))
        .where(Tax.status == "pendiente")
    )
    pending_taxes = float(r.scalar())
    if pending_taxes > 0:
        insights.append({
            "type": "alerta",
            "title": f"Impuestos pendientes: {pending_taxes:.2f}€",
            "description": "Revisa los plazos fiscales para evitar recargos.",
            "severity": "warning",
        })

    # Margin warning
    if income > 0:
        margin_pct = (profit / income) * 100
        if 0 <= margin_pct < 10:
            insights.append({
                "type": "consejo",
                "title": f"Margen bajo: {margin_pct:.1f}%",
                "description": "Considera revisar gastos o ajustar precios.",
                "severity": "warning",
            })

    return insights


async def _sync_insights(db: AsyncSession):
    new_insights = await _build_insights(db)
    # Mark existing unread as dismissed before creating new ones
    r = await db.execute(
        select(FinancialInsight)
        .where(FinancialInsight.is_dismissed.is_(False), FinancialInsight.is_read.is_(False))
    )
    for old in r.scalars().all():
        old.is_dismissed = True

    for data in new_insights:
        insight = FinancialInsight(**data)
        db.add(insight)
    await db.commit()


async def _build_tasks(db: AsyncSession):
    now = datetime.now(timezone.utc)

    # Check for overdue taxes
    r = await db.execute(
        select(Tax).where(Tax.status == "pendiente", Tax.due_date <= now.date())
    )
    for tax in r.scalars().all():
        key = f"tax-overdue-{tax.id}"
        existing = await db.execute(
            select(AdvisorTask).where(AdvisorTask.source_key == key)
        )
        if not existing.scalars().first():
            db.add(AdvisorTask(
                source_key=key,
                title=f"Pagar {tax.name} ({tax.model} {tax.period})",
                description=f"Importe: {tax.tax_amount:.2f}€. Vencimiento: {tax.due_date}",
                priority="high",
                due_date=tax.due_date,
            ))
    await db.commit()


# --- Routes ---

@router.get("/overview", response_model=AdvisorOverview)
async def advisor_overview(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month

    await _sync_insights(db)
    await _build_tasks(db)

    income = await _sum_income_month(db, y, m)
    expenses = await _sum_expenses_month(db, y, m)
    profit = income - expenses
    margin_pct = (profit / income * 100) if income > 0 else 0

    r = await db.execute(
        select(func.coalesce(func.sum(Tax.tax_amount), 0))
        .where(Tax.status == "pendiente")
    )
    pending_taxes = float(r.scalar())

    # Next tax deadline
    r = await db.execute(
        select(Tax.due_date)
        .where(Tax.status == "pendiente", Tax.due_date >= now.date())
        .order_by(Tax.due_date)
        .limit(1)
    )
    next_deadline = r.scalars().first()

    r = await db.execute(
        select(func.count())
        .select_from(FinancialInsight)
        .where(FinancialInsight.is_read.is_(False), FinancialInsight.is_dismissed.is_(False))
    )
    unread = r.scalar()

    r = await db.execute(
        select(func.count())
        .select_from(AdvisorTask)
        .where(AdvisorTask.status == "open")
    )
    open_tasks = r.scalar()

    return AdvisorOverview(
        total_income_month=round(income, 2),
        total_expenses_month=round(expenses, 2),
        net_profit_month=round(profit, 2),
        margin_pct=round(margin_pct, 1),
        pending_taxes=round(pending_taxes, 2),
        next_tax_deadline=next_deadline,
        unread_insights=unread or 0,
        open_tasks=open_tasks or 0,
    )


@router.get("/insights", response_model=list[FinancialInsightResponse])
async def list_insights(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(
        select(FinancialInsight)
        .where(FinancialInsight.is_dismissed.is_(False))
        .order_by(FinancialInsight.created_at.desc())
        .limit(50)
    )
    return [FinancialInsightResponse.model_validate(i) for i in r.scalars().all()]


@router.put("/insights/{insight_id}/read")
async def mark_insight_read(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(select(FinancialInsight).where(FinancialInsight.id == insight_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Insight no encontrado")
    item.is_read = True
    await db.commit()
    return {"ok": True}


@router.put("/insights/{insight_id}/dismiss")
async def dismiss_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(select(FinancialInsight).where(FinancialInsight.id == insight_id))
    item = r.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Insight no encontrado")
    item.is_dismissed = True
    await db.commit()
    return {"ok": True}


@router.get("/tasks", response_model=list[AdvisorTaskResponse])
async def list_tasks(
    task_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    q = select(AdvisorTask)
    if task_status:
        q = q.where(AdvisorTask.status == task_status)
    q = q.order_by(AdvisorTask.created_at.desc())
    r = await db.execute(q)
    return [AdvisorTaskResponse.model_validate(t) for t in r.scalars().all()]


@router.post("/tasks", response_model=AdvisorTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: AdvisorTaskCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    task = AdvisorTask(**data.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return AdvisorTaskResponse.model_validate(task)


class TaskStatusUpdate(BaseModel):
    status: str


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    data: TaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(select(AdvisorTask).where(AdvisorTask.id == task_id))
    task = r.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    task.status = data.status
    await db.commit()
    return {"ok": True}


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(select(AdvisorTask).where(AdvisorTask.id == task_id))
    task = r.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    await db.delete(task)
    await db.commit()


@router.get("/ai-briefs", response_model=list[AdvisorAiBriefResponse])
async def list_briefs(
    limit: int = Query(default=10),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    r = await db.execute(
        select(AdvisorAiBrief).order_by(AdvisorAiBrief.created_at.desc()).limit(limit)
    )
    return [AdvisorAiBriefResponse.model_validate(b) for b in r.scalars().all()]


@router.get("/monthly-close")
async def get_monthly_close(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    r = await db.execute(
        select(MonthlyClose).where(and_(MonthlyClose.year == y, MonthlyClose.month == m))
    )
    record = r.scalars().first()
    if record is None:
        record = MonthlyClose(year=y, month=m)
        db.add(record)
        await db.commit()
        await db.refresh(record)
    return MonthlyCloseResponse(
        year=record.year,
        month=record.month,
        reviewed_numbers=record.reviewed_numbers,
        reviewed_margin=record.reviewed_margin,
        reviewed_cash_buffer=record.reviewed_cash_buffer,
        reviewed_reinvestment=record.reviewed_reinvestment,
        reviewed_debt=record.reviewed_debt,
        reviewed_taxes=record.reviewed_taxes,
        reviewed_personal=record.reviewed_personal,
        responsible_name=record.responsible_name or "",
        notes=record.notes or "",
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


@router.put("/monthly-close")
async def update_monthly_close(
    body: MonthlyCloseUpdate,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_advisor")),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    r = await db.execute(
        select(MonthlyClose).where(and_(MonthlyClose.year == y, MonthlyClose.month == m))
    )
    record = r.scalars().first()
    if record is None:
        record = MonthlyClose(year=y, month=m)
        db.add(record)
        await db.commit()
        await db.refresh(record)

    updates = body.model_dump(exclude_unset=True)
    for field in (
        "reviewed_numbers", "reviewed_margin", "reviewed_cash_buffer",
        "reviewed_reinvestment", "reviewed_debt", "reviewed_taxes", "reviewed_personal",
    ):
        if field in updates:
            setattr(record, field, bool(updates[field]))
    if "responsible_name" in updates:
        record.responsible_name = updates["responsible_name"] or ""
    if "notes" in updates:
        record.notes = updates["notes"] or ""

    await db.commit()
    await db.refresh(record)
    return {"ok": True}
