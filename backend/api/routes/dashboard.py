from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone
from calendar import monthrange

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select, func, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Client,
    ClientStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    MonthlyClose,
    FinancialSettings,
)
from backend.schemas.dashboard import (
    DashboardOverview,
    ClientProfitability,
    ProfitabilityResponse,
    TeamMemberSummary,
    MonthlyCloseResponse,
    MonthlyCloseUpdate,
    FinancialSettingsResponse,
    FinancialSettingsUpdate,
)
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _month_range(year: int, month: int):
    _, last_day = monthrange(year, month)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


async def _get_or_create_financial_settings(db: AsyncSession) -> FinancialSettings:
    r = await db.execute(select(FinancialSettings))
    record = r.scalars().first()
    if record is None:
        record = FinancialSettings()
        db.add(record)
        await db.commit()
        await db.refresh(record)
    return record


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start, end = _month_range(y, m)

    # Active clients
    r = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == ClientStatus.active)
    )
    active_clients = r.scalar()

    # Tasks
    r = await db.execute(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.pending)
    )
    pending_tasks = r.scalar()

    r = await db.execute(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.in_progress)
    )
    in_progress_tasks = r.scalar()

    # Hours this month
    r = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            and_(TimeEntry.minutes.isnot(None), TimeEntry.date >= start, TimeEntry.date <= end)
        )
    )
    hours_this_month = round((r.scalar() or 0) / 60, 1)

    # Total budget (active clients)
    r = await db.execute(
        select(func.coalesce(func.sum(Client.monthly_budget), 0)).where(
            Client.status == ClientStatus.active
        )
    )
    total_budget = r.scalar() or 0

    # Total cost this month (hours * hourly_rate)
    r = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0)).select_from(
            TimeEntry
        ).join(User, TimeEntry.user_id == User.id).where(
            and_(TimeEntry.minutes.isnot(None), TimeEntry.date >= start, TimeEntry.date <= end)
        )
    )
    total_cost = round(r.scalar() or 0, 2)
    margin = round((total_budget - total_cost), 2)
    margin_percent = round((margin / total_budget * 100) if total_budget > 0 else 0, 1)

    return DashboardOverview(
        active_clients=active_clients,
        pending_tasks=pending_tasks,
        in_progress_tasks=in_progress_tasks,
        hours_this_month=hours_this_month,
        total_budget=total_budget,
        total_cost=total_cost,
        margin=margin,
        margin_percent=margin_percent,
    )


@router.get("/profitability", response_model=ProfitabilityResponse)
async def get_profitability(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start, end = _month_range(y, m)

    # Get active clients
    r = await db.execute(select(Client).where(Client.status == ClientStatus.active))
    clients = r.scalars().all()

    result = []
    for client in clients:
        budget = client.monthly_budget or 0

        # Actual minutes + cost for this client this month
        r = await db.execute(
            select(
                func.coalesce(func.sum(TimeEntry.minutes), 0),
                func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0),
            )
            .select_from(TimeEntry)
            .join(Task, TimeEntry.task_id == Task.id)
            .join(User, TimeEntry.user_id == User.id)
            .where(
                and_(
                    Task.client_id == client.id,
                    TimeEntry.minutes.isnot(None),
                    TimeEntry.date >= start,
                    TimeEntry.date <= end,
                )
            )
        )
        actual_minutes, cost_val = r.first() or (0, 0)
        actual_minutes = int(actual_minutes or 0)
        cost = round(cost_val or 0, 2)

        # Estimated minutes for tasks created in the period
        r = await db.execute(
            select(func.coalesce(func.sum(Task.estimated_minutes), 0)).where(
                and_(
                    Task.client_id == client.id,
                    Task.created_at >= start,
                    Task.created_at <= end,
                )
            )
        )
        estimated_minutes = int(r.scalar() or 0)
        variance_minutes = actual_minutes - estimated_minutes
        margin = round(budget - cost, 2)
        margin_pct = round((margin / budget * 100) if budget > 0 else 0, 1)

        if margin_pct >= 20:
            s = "profitable"
        elif margin_pct >= 0:
            s = "at_risk"
        else:
            s = "unprofitable"

        result.append(ClientProfitability(
            client_id=client.id,
            client_name=client.name,
            budget=budget,
            cost=cost,
            margin=margin,
            margin_percent=margin_pct,
            estimated_minutes=estimated_minutes,
            actual_minutes=actual_minutes,
            variance_minutes=variance_minutes,
            status=s,
        ))

    return ProfitabilityResponse(clients=result)


@router.get("/team", response_model=list[TeamMemberSummary])
async def get_team_summary(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    start, end = _month_range(y, m)

    r = await db.execute(select(User).order_by(User.full_name))
    users = r.scalars().all()

    result = []
    for user in users:
        # Hours this month
        r = await db.execute(
            select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
                and_(
                    TimeEntry.user_id == user.id,
                    TimeEntry.minutes.isnot(None),
                    TimeEntry.date >= start,
                    TimeEntry.date <= end,
                )
            )
        )
        total_minutes = r.scalar() or 0
        hours = round(total_minutes / 60, 1)
        cost = round(hours * (user.hourly_rate or 0), 2)

        # Task count
        r = await db.execute(
            select(func.count(distinct(TimeEntry.task_id))).where(
                and_(
                    TimeEntry.user_id == user.id,
                    TimeEntry.minutes.isnot(None),
                    TimeEntry.date >= start,
                    TimeEntry.date <= end,
                )
            )
        )
        task_count = r.scalar() or 0

        # Clients touched
        r = await db.execute(
            select(func.count(distinct(Task.client_id)))
            .select_from(TimeEntry)
            .join(Task, TimeEntry.task_id == Task.id)
            .where(
                and_(
                    TimeEntry.user_id == user.id,
                    TimeEntry.minutes.isnot(None),
                    TimeEntry.date >= start,
                    TimeEntry.date <= end,
                )
            )
        )
        clients_touched = r.scalar() or 0

        result.append(TeamMemberSummary(
            user_id=user.id,
            full_name=user.full_name,
            hourly_rate=user.hourly_rate,
            hours_this_month=hours,
            cost=cost,
            task_count=task_count,
            clients_touched=clients_touched,
        ))

    return result


@router.get("/monthly-close", response_model=MonthlyCloseResponse)
async def get_monthly_close(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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

    return _monthly_close_response(record)


def _monthly_close_response(record: MonthlyClose) -> MonthlyCloseResponse:
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


@router.put("/monthly-close", response_model=MonthlyCloseResponse)
async def update_monthly_close(
    body: MonthlyCloseUpdate,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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

    return _monthly_close_response(record)


@router.get("/monthly-close/export")
async def export_monthly_close(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
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

    payload = {
        "year": record.year,
        "month": record.month,
        "reviewed_numbers": record.reviewed_numbers,
        "reviewed_margin": record.reviewed_margin,
        "reviewed_cash_buffer": record.reviewed_cash_buffer,
        "reviewed_reinvestment": record.reviewed_reinvestment,
        "reviewed_debt": record.reviewed_debt,
        "reviewed_taxes": record.reviewed_taxes,
        "reviewed_personal": record.reviewed_personal,
        "responsible_name": record.responsible_name or "",
        "notes": record.notes or "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }

    lines = ["campo,valor"]
    for key, value in payload.items():
        lines.append(f"{key},{value}")
    content = "\n".join(lines)
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=cierre-mensual-{y}-{m:02d}.csv"},
    )


@router.get("/financial-settings", response_model=FinancialSettingsResponse)
async def get_financial_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = await _get_or_create_financial_settings(db)
    return _financial_settings_response(record)


def _financial_settings_response(record: FinancialSettings) -> FinancialSettingsResponse:
    utilization = (record.credit_used / record.credit_limit * 100) if record.credit_limit > 0 else 0.0
    return FinancialSettingsResponse(
        tax_reserve=record.tax_reserve,
        credit_limit=record.credit_limit,
        credit_used=record.credit_used,
        credit_utilization=round(utilization, 2),
        monthly_close_day=record.monthly_close_day,
        credit_alert_pct=record.credit_alert_pct,
        tax_reserve_target_pct=record.tax_reserve_target_pct,
        default_vat_rate=record.default_vat_rate,
        corporate_tax_rate=record.corporate_tax_rate,
        irpf_retention_rate=record.irpf_retention_rate,
        cash_start=record.cash_start,
        advisor_expense_alert_pct=record.advisor_expense_alert_pct,
        advisor_margin_warning_pct=record.advisor_margin_warning_pct,
        ai_provider=record.ai_provider,
        ai_model=record.ai_model,
        ai_api_url=record.ai_api_url,
    )


@router.put("/financial-settings", response_model=FinancialSettingsResponse)
async def update_financial_settings(
    body: FinancialSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = await _get_or_create_financial_settings(db)
    updates = body.model_dump(exclude_unset=True)
    float_fields = (
        "tax_reserve", "credit_limit", "credit_used", "credit_alert_pct",
        "tax_reserve_target_pct", "default_vat_rate", "corporate_tax_rate",
        "irpf_retention_rate", "cash_start", "advisor_expense_alert_pct",
        "advisor_margin_warning_pct",
    )
    for field in float_fields:
        if field in updates:
            setattr(record, field, float(updates[field]))
    if "monthly_close_day" in updates:
        record.monthly_close_day = int(updates["monthly_close_day"])
    for field in ("ai_provider", "ai_model", "ai_api_url", "ai_api_key"):
        if field in updates:
            setattr(record, field, updates[field] or "")

    await db.commit()
    await db.refresh(record)
    return _financial_settings_response(record)
