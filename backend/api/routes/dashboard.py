from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, or_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Client,
    ClientStatus,
    DailyUpdate,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
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
from backend.api.deps import get_current_user, require_module, require_admin
from backend.core.security import encrypt_vault_secret
from backend.services.csv_utils import build_csv_response
from backend.api.utils.db_helpers import safe_refresh
from backend.services.report_period import (
    MAX_REPORT_YEAR,
    MIN_REPORT_YEAR,
    month_range_naive,
    resolve_default_period,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def _get_or_create_financial_settings(db: AsyncSession) -> FinancialSettings:
    r = await db.execute(select(FinancialSettings))
    record = r.scalars().first()
    if record is None:
        record = FinancialSettings()
        db.add(record)
        await db.commit()
        await safe_refresh(db, record, log_context="dashboard")
    return record


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("dashboard")),
):
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Active clients
    r = await db.execute(
        select(func.count()).select_from(Client).where(
            Client.status == ClientStatus.active,
            Client.is_internal == False,
        )
    )
    active_clients = r.scalar()

    # Tasks — scoped to the selected month (by scheduled_date, or due_date if no scheduled)
    task_date_filter = or_(
        and_(Task.scheduled_date.isnot(None), Task.scheduled_date >= start, Task.scheduled_date <= end),
        and_(Task.scheduled_date.is_(None), Task.due_date.isnot(None), Task.due_date >= start, Task.due_date <= end),
    )
    r = await db.execute(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.pending, task_date_filter)
    )
    pending_tasks = r.scalar()

    r = await db.execute(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.in_progress, task_date_filter)
    )
    in_progress_tasks = r.scalar()

    # Hours this month
    r = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            and_(TimeEntry.minutes.isnot(None), TimeEntry.date >= start, TimeEntry.date <= end)
        )
    )
    hours_this_month = round((r.scalar() or 0) / 60, 1)

    # Total budget — derived from active projects' monthly_fee (fallback to client.monthly_budget)
    r = await db.execute(
        select(
            Client.id,
            func.coalesce(func.sum(Project.monthly_fee), 0).label("project_fee"),
            Client.monthly_budget,
        )
        .outerjoin(Project, and_(Project.client_id == Client.id, Project.status == ProjectStatus.active))
        .where(Client.status == ClientStatus.active, Client.is_internal == False)
        .group_by(Client.id, Client.monthly_budget)
    )
    total_budget = sum(
        float(row.project_fee) if float(row.project_fee) > 0 else float(row.monthly_budget or 0)
        for row in r.all()
    )

    # Total cost this month (hours * hourly_rate)
    r = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0)).select_from(
            TimeEntry
        ).join(User, TimeEntry.user_id == User.id).where(
            and_(TimeEntry.minutes.isnot(None), TimeEntry.date >= start, TimeEntry.date <= end)
        )
    )
    total_cost = round(float(r.scalar() or 0), 2)
    margin = round(float(total_budget) - float(total_cost), 2)
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
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Get active clients (1 query)
    r = await db.execute(select(Client).where(
        Client.status == ClientStatus.active,
        Client.is_internal == False,
    ))
    clients = r.scalars().all()
    client_ids = [c.id for c in clients]

    if not client_ids:
        return ProfitabilityResponse(clients=[])

    # Aggregate monthly_fee from active projects per client (1 query)
    r = await db.execute(
        select(
            Project.client_id,
            func.coalesce(func.sum(Project.monthly_fee), 0).label("total_fee"),
        )
        .where(
            Project.client_id.in_(client_ids),
            Project.status == ProjectStatus.active,
        )
        .group_by(Project.client_id)
    )
    fee_map = {row.client_id: round(float(row.total_fee), 2) for row in r.all()}

    # Aggregate actual minutes + cost per client (1 query instead of N)
    r = await db.execute(
        select(
            Task.client_id,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("actual_minutes"),
            func.coalesce(func.sum(TimeEntry.minutes * User.hourly_rate / 60), 0).label("cost"),
        )
        .select_from(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            Task.client_id.in_(client_ids),
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start,
            TimeEntry.date <= end,
        )
        .group_by(Task.client_id)
    )
    time_map = {row.client_id: (int(row.actual_minutes), round(float(row.cost), 2)) for row in r.all()}

    # Aggregate estimated minutes per client (1 query instead of N)
    r = await db.execute(
        select(
            Task.client_id,
            func.coalesce(func.sum(Task.estimated_minutes), 0).label("est"),
        )
        .where(
            Task.client_id.in_(client_ids),
            Task.created_at >= start,
            Task.created_at <= end,
        )
        .group_by(Task.client_id)
    )
    est_map = {row.client_id: int(row.est) for row in r.all()}

    # Build response using dict lookups (no per-client queries)
    result = []
    for client in clients:
        # Prefer sum of project fees; fall back to legacy client.monthly_budget
        budget = fee_map.get(client.id, 0) or float(client.monthly_budget or 0)
        actual_minutes, cost = time_map.get(client.id, (0, 0))
        estimated_minutes = est_map.get(client.id, 0)
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
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("dashboard")),
):
    y, m = resolve_default_period(year, month)
    start, end = month_range_naive(y, m)

    # Get users (1 query)
    r = await db.execute(select(User).order_by(User.full_name))
    users = r.scalars().all()

    # Aggregate all metrics per user in a single query (instead of 3N queries)
    r = await db.execute(
        select(
            TimeEntry.user_id,
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("total_minutes"),
            func.count(distinct(TimeEntry.task_id)).label("task_count"),
            func.count(distinct(Task.client_id)).label("clients_touched"),
        )
        .select_from(TimeEntry)
        .outerjoin(Task, TimeEntry.task_id == Task.id)
        .where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start,
            TimeEntry.date <= end,
        )
        .group_by(TimeEntry.user_id)
    )
    metrics_map = {
        row.user_id: (int(row.total_minutes), int(row.task_count), int(row.clients_touched))
        for row in r.all()
    }

    # Build response using dict lookups (no per-user queries)
    result = []
    for user in users:
        total_minutes, task_count, clients_touched = metrics_map.get(user.id, (0, 0, 0))
        hours = round(total_minutes / 60, 1)
        cost = round(hours * float(user.hourly_rate or 0), 2)

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
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    y, m = resolve_default_period(year, month)

    r = await db.execute(
        select(MonthlyClose).where(and_(MonthlyClose.year == y, MonthlyClose.month == m))
    )
    record = r.scalars().first()
    if record is None:
        record = MonthlyClose(year=y, month=m)
        db.add(record)
        await db.commit()
        await safe_refresh(db, record, log_context="dashboard")

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
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("dashboard")),
):
    y, m = resolve_default_period(year, month)

    r = await db.execute(
        select(MonthlyClose).where(and_(MonthlyClose.year == y, MonthlyClose.month == m))
    )
    record = r.scalars().first()
    if record is None:
        record = MonthlyClose(year=y, month=m)
        db.add(record)
        await db.commit()
        await safe_refresh(db, record, log_context="dashboard")

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
    await safe_refresh(db, record, log_context="dashboard")

    return _monthly_close_response(record)


@router.get("/monthly-close/export")
async def export_monthly_close(
    year: Optional[int] = Query(None, ge=MIN_REPORT_YEAR, le=MAX_REPORT_YEAR),
    month: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    y, m = resolve_default_period(year, month)
    r = await db.execute(
        select(MonthlyClose).where(and_(MonthlyClose.year == y, MonthlyClose.month == m))
    )
    record = r.scalars().first()
    if record is None:
        record = MonthlyClose(year=y, month=m)
        db.add(record)
        await db.commit()
        await safe_refresh(db, record, log_context="dashboard")

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

    csv_rows = ([key, value] for key, value in payload.items())
    return build_csv_response(
        f"cierre-mensual-{y}-{m:02d}.csv",
        ["campo", "valor"],
        csv_rows,
    )


@router.get("/financial-settings", response_model=FinancialSettingsResponse)
async def get_financial_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = await _get_or_create_financial_settings(db)
    return _financial_settings_response(record)


def _financial_settings_response(record: FinancialSettings) -> FinancialSettingsResponse:
    utilization = (float(record.credit_used) / float(record.credit_limit) * 100) if record.credit_limit > 0 else 0.0
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
    _: User = Depends(require_admin),
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
    for field in ("ai_provider", "ai_model", "ai_api_url"):
        if field in updates:
            setattr(record, field, updates[field] or "")
    if "ai_api_key" in updates:
        raw_key = updates["ai_api_key"] or ""
        record.ai_api_key = encrypt_vault_secret(raw_key) if raw_key else ""

    await db.commit()
    await safe_refresh(db, record, log_context="dashboard")
    return _financial_settings_response(record)


@router.get("/capacity")
async def get_capacity(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Team capacity: assigned hours vs available hours per active member."""
    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.full_name)
    )
    users = users_result.scalars().all()

    # Single aggregate query for all users (fix N+1)
    task_stats_result = await db.execute(
        select(
            Task.assigned_to,
            func.coalesce(func.sum(Task.estimated_minutes), 0),
            func.count(),
        )
        .where(Task.status.in_([TaskStatus.backlog, TaskStatus.pending, TaskStatus.in_progress, TaskStatus.waiting, TaskStatus.in_review]))
        .group_by(Task.assigned_to)
    )
    stats_map = {row[0]: (row[1] or 0, row[2] or 0) for row in task_stats_result.all()}

    capacity = []
    for user in users:
        assigned_minutes, task_count = stats_map.get(user.id, (0, 0))

        weekly_minutes = (user.weekly_hours or 40) * 60
        load_pct = round((assigned_minutes / weekly_minutes) * 100) if weekly_minutes > 0 else 0

        if load_pct < 70:
            status = "available"
        elif load_pct < 90:
            status = "busy"
        else:
            status = "overloaded"

        capacity.append({
            "user_id": user.id,
            "full_name": user.full_name,
            "weekly_hours": user.weekly_hours or 40,
            "assigned_minutes": assigned_minutes,
            "task_count": task_count,
            "load_percent": load_pct,
            "status": status,
        })

    return capacity


@router.get("/capacity/detail")
async def get_capacity_detail(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Enhanced capacity: per-user task list grouped by client, with priorities."""
    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.full_name)
    )
    users = users_result.scalars().all()
    user_ids = [u.id for u in users]

    if not user_ids:
        return []

    # Fetch all active tasks for these users
    active_statuses = [TaskStatus.backlog, TaskStatus.pending, TaskStatus.in_progress, TaskStatus.waiting, TaskStatus.in_review]
    tasks_result = await db.execute(
        select(Task, Client.name.label("client_name"), Project.name.label("project_name"))
        .outerjoin(Client, Task.client_id == Client.id)
        .outerjoin(Project, Task.project_id == Project.id)
        .where(Task.assigned_to.in_(user_ids), Task.status.in_(active_statuses))
        .order_by(Task.priority.desc(), Task.due_date.asc().nullslast())
    )

    # Group tasks by user
    user_tasks: dict[int, list] = {uid: [] for uid in user_ids}
    for task, client_name, project_name in tasks_result.all():
        user_tasks.setdefault(task.assigned_to, []).append({
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value if task.status else "pending",
            "priority": task.priority.value if task.priority else "medium",
            "estimated_minutes": task.estimated_minutes or 0,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "client_id": task.client_id,
            "client_name": client_name,
            "project_id": task.project_id,
            "project_name": project_name,
        })

    result = []
    for user in users:
        tasks = user_tasks.get(user.id, [])
        assigned_minutes = sum(t["estimated_minutes"] for t in tasks)
        weekly_minutes = (user.weekly_hours or 40) * 60
        load_pct = round((assigned_minutes / weekly_minutes) * 100) if weekly_minutes > 0 else 0

        if load_pct < 70:
            status = "available"
        elif load_pct < 90:
            status = "busy"
        else:
            status = "overloaded"

        # Group tasks by client
        by_client: dict[int | None, dict] = {}
        for t in tasks:
            cid = t["client_id"]
            if cid not in by_client:
                by_client[cid] = {
                    "client_id": cid,
                    "client_name": t["client_name"] or "Sin cliente",
                    "tasks": [],
                    "total_minutes": 0,
                }
            by_client[cid]["tasks"].append(t)
            by_client[cid]["total_minutes"] += t["estimated_minutes"]

        result.append({
            "user_id": user.id,
            "full_name": user.full_name,
            "weekly_hours": user.weekly_hours or 40,
            "assigned_minutes": assigned_minutes,
            "task_count": len(tasks),
            "load_percent": load_pct,
            "status": status,
            "clients": sorted(by_client.values(), key=lambda c: -c["total_minutes"]),
        })

    return result


# ── Utilization (real hours vs available) ────────────────────────────────────

@router.get("/utilization")
async def get_utilization(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("dashboard")),
):
    """Team utilization: actual hours logged vs available hours.

    Returns per-user utilization for the given month + global average.
    """
    from datetime import date, timedelta
    import calendar

    today = date.today()
    y = year or today.year
    m = month or today.month
    days_in_month = calendar.monthrange(y, m)[1]
    start = date(y, m, 1)
    end = date(y, m, days_in_month)

    # Count business days in month
    business_days = sum(1 for d in range(days_in_month)
                        if date(y, m, d + 1).weekday() < 5)

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.full_name)
    )
    users = users_result.scalars().all()

    # Aggregate logged hours per user for the month
    hours_result = await db.execute(
        select(
            TimeEntry.user_id,
            func.coalesce(func.sum(TimeEntry.minutes), 0),
        ).where(
            func.date(TimeEntry.date) >= start,
            func.date(TimeEntry.date) <= end,
        ).group_by(TimeEntry.user_id)
    )
    hours_map = {row[0]: row[1] for row in hours_result.all()}

    members = []
    total_logged = 0
    total_available = 0

    for user in users:
        daily_hours = (user.weekly_hours or 40) / 5
        available_minutes = int(daily_hours * 60 * business_days)
        logged_minutes = hours_map.get(user.id, 0)
        pct = round((logged_minutes / available_minutes) * 100) if available_minutes > 0 else 0

        total_logged += logged_minutes
        total_available += available_minutes

        members.append({
            "user_id": user.id,
            "full_name": user.full_name,
            "logged_minutes": logged_minutes,
            "available_minutes": available_minutes,
            "utilization_pct": pct,
        })

    global_pct = round((total_logged / total_available) * 100) if total_available > 0 else 0

    return {
        "year": y,
        "month": m,
        "business_days": business_days,
        "global_utilization_pct": global_pct,
        "total_logged_hours": round(total_logged / 60, 1),
        "total_available_hours": round(total_available / 60, 1),
        "members": sorted(members, key=lambda x: x["utilization_pct"], reverse=True),
    }


# ── Today Block ──────────────────────────────────────────────────────────────

@router.get("/today")
async def get_today(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tasks scheduled for today, grouped by user. Returns all users' tasks for admin, own for member."""
    from datetime import date
    today = date.today()

    query = (
        select(Task)
        .where(Task.scheduled_date == today)
        .where(Task.status != TaskStatus.completed)
    )
    if current_user.role != "admin":
        query = query.where(Task.assigned_to == current_user.id)

    result = await db.execute(query.order_by(Task.priority.asc()))
    tasks = result.scalars().all()

    # Group by assignee
    by_user: dict[str, list] = {}
    for t in tasks:
        user_name = t.assigned_user.full_name if t.assigned_user else "Sin asignar"
        if user_name not in by_user:
            by_user[user_name] = []
        by_user[user_name].append({
            "id": t.id,
            "title": t.title,
            "status": t.status.value,
            "priority": t.priority.value,
            "client_name": t.client.name if t.client else None,
            "estimated_minutes": t.estimated_minutes,
        })

    return {
        "date": today.isoformat(),
        "total_tasks": len(tasks),
        "by_user": by_user,
    }


# ---------------------------------------------------------------------------
# GET /alerts-summary — Real-time alert counts for dashboard widget
# ---------------------------------------------------------------------------

@router.get("/alerts-summary")
async def alerts_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("dashboard")),
):
    """Return real-time alert counts for the dashboard widget.

    Categories: overdue_tasks, missing_dailys, incomplete_timesheets,
    clients_no_hours, capacity_overloads.
    """
    from datetime import date, timedelta

    today = date.today()
    alerts: list[dict] = []

    # 1. Overdue tasks (all users, for admin view)
    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.due_date < today,
            Task.status.notin_([TaskStatus.completed]),
        )
    )
    overdue_count = overdue_result.scalar() or 0
    if overdue_count > 0:
        alerts.append({
            "type": "overdue_tasks",
            "severity": "critical" if overdue_count >= 5 else "warning",
            "count": overdue_count,
            "title": f"{overdue_count} tareas vencidas",
            "link": "/tasks?overdue=true",
        })

    # 2. Missing dailys (users with no daily in 2+ business days)
    # On Monday check from Thursday, otherwise 2 calendar days back
    if today.weekday() == 0:  # Monday
        lookback = today - timedelta(days=4)  # Thursday
    elif today.weekday() == 6:  # Sunday — skip alert entirely
        lookback = None
    elif today.weekday() == 5:  # Saturday — skip alert entirely
        lookback = None
    else:
        lookback = today - timedelta(days=2)
    missing_daily_names: list[str] = []
    if lookback is not None:
        active_users_result = await db.execute(
            select(User).where(User.is_active.is_(True), User.role != UserRole.admin)
        )
        active_users = active_users_result.scalars().all()

        # Batch: get user IDs who HAVE submitted a daily since lookback (1 query)
        recent_daily_result = await db.execute(
            select(DailyUpdate.user_id).where(
                DailyUpdate.date >= lookback,
            ).distinct()
        )
        users_with_daily = {row[0] for row in recent_daily_result.all()}

        missing_daily_names = [
            u.full_name for u in active_users
            if u.id not in users_with_daily
        ]
    if missing_daily_names:
        alerts.append({
            "type": "missing_dailys",
            "severity": "warning",
            "count": len(missing_daily_names),
            "title": f"{len(missing_daily_names)} sin daily reciente",
            "detail": missing_daily_names[:5],
            "link": "/dailys",
        })

    # 3. Incomplete timesheets yesterday (< 6h on weekday)
    yesterday = today - timedelta(days=1)
    if yesterday.weekday() < 5:  # Only check weekdays
        all_users_result = await db.execute(
            select(User).where(User.is_active.is_(True), User.role != UserRole.admin)
        )
        all_users = all_users_result.scalars().all()

        # Batch: get hours per user for yesterday (1 query instead of N)
        hours_result = await db.execute(
            select(
                TimeEntry.user_id,
                func.coalesce(func.sum(TimeEntry.minutes), 0).label("total"),
            ).where(
                func.date(TimeEntry.date) == yesterday,
            ).group_by(TimeEntry.user_id)
        )
        hours_map = {row.user_id: row.total for row in hours_result.all()}

        incomplete_names: list[str] = [
            u.full_name for u in all_users
            if hours_map.get(u.id, 0) < 360
        ]
        if incomplete_names:
            alerts.append({
                "type": "incomplete_timesheets",
                "severity": "info",
                "count": len(incomplete_names),
                "title": f"{len(incomplete_names)} timesheets incompletos ayer",
                "detail": incomplete_names[:5],
                "link": "/timesheet",
            })

    # 4. Active clients with 0 hours this week (from Wednesday)
    if today.weekday() >= 2:
        week_start = today - timedelta(days=today.weekday())
        active_clients = await db.execute(
            select(Client).where(Client.status == ClientStatus.active)
        )
        no_hours_clients: list[str] = []
        for client in active_clients.scalars().all():
            hrs = await db.execute(
                select(func.coalesce(func.sum(TimeEntry.minutes), 0))
                .join(Task, TimeEntry.task_id == Task.id)
                .where(
                    Task.client_id == client.id,
                    func.date(TimeEntry.date) >= week_start,
                )
            )
            if (hrs.scalar() or 0) == 0:
                no_hours_clients.append(client.name)
        if no_hours_clients:
            alerts.append({
                "type": "clients_no_hours",
                "severity": "warning",
                "count": len(no_hours_clients),
                "title": f"{len(no_hours_clients)} clientes sin horas esta semana",
                "detail": no_hours_clients[:5],
                "link": "/clients",
            })

    # 5. Capacity overload (20+ hours estimated pending)
    overloaded = await db.execute(
        select(
            Task.assigned_to,
            func.sum(Task.estimated_minutes).label("total"),
        ).where(
            Task.assigned_to.isnot(None),
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            Task.estimated_minutes.isnot(None),
        ).group_by(Task.assigned_to)
    )
    overloaded_names: list[str] = []
    for row in overloaded.all():
        if row.total and row.total > 1200:
            u_res = await db.execute(select(User.full_name).where(User.id == row.assigned_to))
            name = u_res.scalar() or f"#{row.assigned_to}"
            overloaded_names.append(name)
    if overloaded_names:
        alerts.append({
            "type": "capacity_overload",
            "severity": "critical",
            "count": len(overloaded_names),
            "title": f"{len(overloaded_names)} sobrecargados (20h+ pendiente)",
            "detail": overloaded_names[:5],
            "link": "/capacity",
        })

    total = sum(a["count"] for a in alerts)
    critical = sum(a["count"] for a in alerts if a["severity"] == "critical")

    return {
        "total": total,
        "critical": critical,
        "alerts": alerts,
    }
