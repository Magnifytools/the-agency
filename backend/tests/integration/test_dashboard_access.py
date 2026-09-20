"""Dashboard source ACL, financial separation, and civil-period contracts."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.dashboard import update_monthly_close
from backend.config import settings
from backend.db.models import (
    Client, ClientStatus, FinancialSettings, MonthlyClose, Task, TaskPriority, TaskStatus,
    TimeEntry, User, UserRole,
)
from backend.schemas.dashboard import MonthlyCloseUpdate
from backend.services.temporal import business_today, utc_now_naive

pytestmark = pytest.mark.asyncio


async def test_member_overview_marks_unavailable_sources_without_financial_keys(
    make_member_client,
):
    client = await make_member_client([("dashboard", True, False)])
    try:
        response = await client.get("/api/dashboard/overview", params={"year": 2026, "month": 9})
    finally:
        await client.aclose()

    assert response.status_code == 200, response.text
    assert response.json() == {
        "active_clients": None,
        "pending_tasks": None,
        "in_progress_tasks": None,
        "hours_this_month": None,
        "availability": {"clients": False, "tasks": False, "timesheet": False},
        "hours_scope": "unavailable",
    }


async def test_member_hours_are_own_and_admin_hours_include_historical_retired_work(
    make_member_client, admin_client, admin_user, db_session,
):
    member_client = await make_member_client([
        ("dashboard", True, False), ("timesheet", True, False),
    ])
    member = member_client.test_user
    retired = Task(
        title="Trabajo retirado con horas históricas", status=TaskStatus.pending,
        priority=TaskPriority.medium, retired_at=utc_now_naive(), retired_reason="Histórico",
    )
    db_session.add(retired)
    await db_session.flush()
    db_session.add_all([
        TimeEntry(
            user_id=member.id, task_id=retired.id, minutes=30,
            date=datetime(2026, 3, 31, 21, 59), started_at=datetime(2026, 3, 31, 21, 0),
        ),
        TimeEntry(
            user_id=admin_user.id, task_id=retired.id, minutes=60,
            date=datetime(2026, 3, 15, 12), started_at=datetime(2026, 3, 15, 11),
        ),
        # 00:00 Madrid on 1 April after the DST switch: outside March.
        TimeEntry(
            user_id=member.id, task_id=retired.id, minutes=90,
            date=datetime(2026, 3, 31, 22), started_at=datetime(2026, 3, 31, 22),
        ),
    ])
    await db_session.flush()

    try:
        own = await member_client.get(
            "/api/dashboard/overview", params={"year": 2026, "month": 3},
        )
    finally:
        await member_client.aclose()
    assert own.status_code == 200, own.text
    assert own.json()["hours_this_month"] == 0.5
    assert own.json()["hours_scope"] == "mine"
    assert own.json()["availability"] == {
        "clients": False, "tasks": False, "timesheet": True,
    }

    team = await admin_client.get(
        "/api/dashboard/overview", params={"year": 2026, "month": 3},
    )
    assert team.status_code == 200, team.text
    assert team.json()["hours_this_month"] == 1.5
    assert team.json()["hours_scope"] == "team"


async def test_team_and_utilization_are_admin_only(member_client):
    assert (await member_client.get("/api/dashboard/team")).status_code == 403
    assert (await member_client.get("/api/dashboard/utilization")).status_code == 403


async def test_hidden_finance_omits_team_costs_and_blocks_all_financial_routes(
    admin_client, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "finance")
    team = await admin_client.get("/api/dashboard/team")
    assert team.status_code == 200, team.text
    assert all("hourly_rate" not in row and "cost" not in row for row in team.json())

    requests = [
        ("GET", "/api/dashboard/overview/financial"),
        ("GET", "/api/dashboard/profitability"),
        ("GET", "/api/dashboard/monthly-close"),
        ("PUT", "/api/dashboard/monthly-close"),
        ("GET", "/api/dashboard/monthly-close/export"),
        ("GET", "/api/dashboard/financial-settings"),
        ("PUT", "/api/dashboard/financial-settings"),
    ]
    for method, path in requests:
        response = await admin_client.request(method, path, json={} if method == "PUT" else None)
        assert response.status_code == 404, (method, path, response.text)


async def test_financial_overview_is_separate_and_admin_only(
    admin_client, member_client, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    monkeypatch.setattr(settings, "DEFAULT_HOURLY_RATE", 40.0)
    response = await admin_client.get(
        "/api/dashboard/overview/financial", params={"year": 2026, "month": 9},
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"total_budget", "total_cost", "margin", "margin_percent"}
    assert (await member_client.get("/api/dashboard/overview/financial")).status_code == 403


async def test_member_cannot_write_monthly_close_even_with_finance_enabled(
    member_client, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    response = await member_client.put("/api/dashboard/monthly-close", json={"notes": "no"})
    assert response.status_code == 403


async def test_today_does_not_expose_client_name_without_clients_permission(
    make_member_client, db_session,
):
    member_client = await make_member_client([
        ("dashboard", True, False), ("tasks", True, False),
    ])
    member = member_client.test_user
    client = Client(name="Cliente no autorizado")
    db_session.add(client)
    await db_session.flush()
    task = Task(
        title="Trabajo visible", client_id=client.id, assigned_to=member.id,
        created_by=member.id, status=TaskStatus.pending, priority=TaskPriority.medium,
        scheduled_date=business_today(),
    )
    db_session.add(task)
    await db_session.flush()

    try:
        response = await member_client.get("/api/dashboard/today")
    finally:
        await member_client.aclose()
    assert response.status_code == 200, response.text
    rows = [item for group in response.json()["by_user"].values() for item in group]
    assert rows == [{
        "id": task.id,
        "title": "Trabajo visible",
        "status": "pending",
        "priority": "medium",
        "client_name": None,
        "estimated_minutes": None,
    }]


async def test_member_alerts_scope_overdue_tasks_to_self(
    make_member_client, admin_user, db_session,
):
    member_client = await make_member_client([
        ("dashboard", True, False), ("tasks", True, False),
    ])
    member = member_client.test_user
    db_session.add_all([
        Task(
            title="Vencida propia", assigned_to=member.id, created_by=member.id,
            status=TaskStatus.pending, priority=TaskPriority.medium,
            due_date=datetime.combine(business_today() - timedelta(days=1), datetime.min.time()),
        ),
        Task(
            title="Vencida ajena", assigned_to=admin_user.id, created_by=admin_user.id,
            status=TaskStatus.pending, priority=TaskPriority.medium,
            due_date=datetime.combine(business_today() - timedelta(days=1), datetime.min.time()),
        ),
    ])
    await db_session.flush()
    try:
        response = await member_client.get("/api/dashboard/alerts-summary")
    finally:
        await member_client.aclose()
    assert response.status_code == 200, response.text
    overdue = next(item for item in response.json()["alerts"] if item["type"] == "overdue_tasks")
    assert overdue["count"] == 1


async def test_operational_task_count_excludes_retired_and_recurrence_templates(
    make_member_client, db_session,
):
    member_client = await make_member_client([
        ("dashboard", True, False), ("tasks", True, False),
    ])
    member = member_client.test_user
    day = business_today()
    common = {
        "status": TaskStatus.pending,
        "priority": TaskPriority.medium,
        "scheduled_date": day,
        "assigned_to": member.id,
        "created_by": member.id,
    }
    db_session.add_all([
        Task(title="Operativa", **common),
        Task(
            title="Retirada", retired_at=utc_now_naive(), retired_reason="Fuera",
            **common,
        ),
        Task(title="Plantilla", is_recurring=True, recurrence_pattern="weekly", **common),
    ])
    await db_session.flush()
    try:
        response = await member_client.get(
            "/api/dashboard/overview", params={"year": day.year, "month": day.month},
        )
    finally:
        await member_client.aclose()
    assert response.status_code == 200, response.text
    assert response.json()["pending_tasks"] == 1
    assert response.json()["availability"]["tasks"] is True


async def test_disabled_source_is_unavailable_even_for_admin(
    admin_client, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "tasks")
    overview = await admin_client.get("/api/dashboard/overview")
    assert overview.status_code == 200, overview.text
    assert overview.json()["pending_tasks"] is None
    assert overview.json()["in_progress_tasks"] is None
    assert overview.json()["availability"]["tasks"] is False
    assert (await admin_client.get("/api/dashboard/today")).status_code == 404
    assert (await admin_client.get("/api/dashboard/overview/financial")).status_code == 200
    assert (await admin_client.get("/api/dashboard/profitability")).status_code == 404
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "clients")
    assert (await admin_client.get("/api/dashboard/overview/financial")).status_code == 404


async def test_monthly_close_reads_do_not_write_and_holded_roundtrips(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    params = {"year": 2096, "month": 7}
    before = await db_session.scalar(select(func.count()).select_from(MonthlyClose))
    response = await admin_client.get("/api/dashboard/monthly-close", params=params)
    export = await admin_client.get("/api/dashboard/monthly-close/export", params=params)
    assert response.status_code == export.status_code == 200
    assert response.json()["reviewed_holded"] is False
    assert await db_session.scalar(select(func.count()).select_from(MonthlyClose)) == before

    updated = await admin_client.put(
        "/api/dashboard/monthly-close", params=params,
        json={"reviewed_holded": True, "notes": "Holded revisado"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["reviewed_holded"] is True
    loaded = await admin_client.get("/api/dashboard/monthly-close", params=params)
    assert loaded.json()["reviewed_holded"] is True
    exported = await admin_client.get("/api/dashboard/monthly-close/export", params=params)
    assert "reviewed_holded,True" in exported.text


async def test_concurrent_first_monthly_close_updates_create_one_row(engine):
    year, month = 2097, 8

    async def update(body):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            return await update_monthly_close(
                MonthlyCloseUpdate(**body), year=year, month=month, db=db, _=None,
            )

    first, second = await asyncio.gather(
        update({"reviewed_holded": True}),
        update({"reviewed_numbers": True}),
    )
    assert first.year == second.year == year
    async with AsyncSession(engine) as verify:
        rows = (await verify.scalars(select(MonthlyClose).where(
            MonthlyClose.year == year, MonthlyClose.month == month,
        ))).all()
        assert len(rows) == 1
        assert rows[0].reviewed_holded is True
        assert rows[0].reviewed_numbers is True
        await verify.execute(delete(MonthlyClose).where(MonthlyClose.id == rows[0].id))
        await verify.commit()


async def test_financial_settings_get_does_not_create_singleton(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    await db_session.execute(delete(FinancialSettings))
    await db_session.flush()
    response = await admin_client.get("/api/dashboard/financial-settings")
    assert response.status_code == 200, response.text
    assert response.json()["monthly_close_day"] == 5
    assert await db_session.scalar(select(func.count()).select_from(FinancialSettings)) == 0


async def test_zero_capacity_is_explicit_and_period_validation_is_shared(
    admin_client, admin_user, db_session,
):
    admin_user.weekly_hours = 0
    await db_session.flush()
    capacity = await admin_client.get("/api/dashboard/capacity")
    detail = await admin_client.get("/api/dashboard/capacity/detail")
    utilization = await admin_client.get(
        "/api/dashboard/utilization", params={"year": 2026, "month": 9},
    )
    for response in (capacity, detail, utilization):
        assert response.status_code == 200, response.text
    row = next(item for item in capacity.json() if item["user_id"] == admin_user.id)
    assert (row["weekly_hours"], row["load_percent"], row["status"]) == (0, None, "no_capacity")
    detail_row = next(item for item in detail.json() if item["user_id"] == admin_user.id)
    assert (detail_row["weekly_hours"], detail_row["load_percent"], detail_row["status"]) == (0, None, "no_capacity")
    utilization_row = next(item for item in utilization.json()["members"] if item["user_id"] == admin_user.id)
    assert utilization_row["available_minutes"] == 0
    assert utilization_row["utilization_pct"] is None
    assert utilization.json()["global_utilization_pct"] is None
    assert (await admin_client.get("/api/dashboard/utilization", params={"month": 13})).status_code == 422
    assert (await admin_client.get("/api/dashboard/utilization", params={"year": 1999})).status_code == 422


async def test_clients_without_hours_alert_is_team_only(
    make_member_client, admin_client, db_session, monkeypatch,
):
    # This alert is deliberately available only from Wednesday. Freeze the
    # business day so the ACL assertion does not depend on the CI weekday.
    import backend.api.routes.dashboard as dashboard_route

    monkeypatch.setattr(dashboard_route, "business_today", lambda: date(2026, 9, 23))
    member_client = await make_member_client([
        ("dashboard", True, False), ("clients", True, False),
        ("tasks", True, False), ("timesheet", True, False),
    ])
    db_session.add(Client(name="Cliente sin horas", status=ClientStatus.active))
    await db_session.flush()
    try:
        member = await member_client.get("/api/dashboard/alerts-summary")
    finally:
        await member_client.aclose()
    admin = await admin_client.get("/api/dashboard/alerts-summary")
    assert member.status_code == admin.status_code == 200
    assert "clients_no_hours" not in {item["type"] for item in member.json()["alerts"]}
    assert "clients_no_hours" in {item["type"] for item in admin.json()["alerts"]}


async def test_team_cost_matches_financial_aggregates_with_exact_minutes_and_rate_fallback(
    admin_client, admin_user, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "")
    admin_user.hourly_rate = None
    configured_rate = User(
        email="team-rate-30@example.com", hashed_password="x", full_name="Tarifa 30",
        role=UserRole.member, is_active=True, hourly_rate=30,
    )
    zero_rate = User(
        email="team-rate-zero@example.com", hashed_password="x", full_name="Tarifa cero",
        role=UserRole.member, is_active=True, hourly_rate=0,
    )
    client = Client(
        name="Costes coherentes", status=ClientStatus.active, monthly_budget=1000,
    )
    db_session.add_all([configured_rate, zero_rate, client])
    await db_session.flush()

    users = [admin_user, configured_rate, zero_rate]
    tasks = [
        Task(
            title=f"Trabajo de {user.full_name}", status=TaskStatus.pending,
            priority=TaskPriority.medium, client_id=client.id, assigned_to=user.id,
        )
        for user in users
    ]
    db_session.add_all(tasks)
    await db_session.flush()
    db_session.add_all([
        TimeEntry(
            user_id=user.id, task_id=task.id, minutes=29,
            date=datetime(2026, 9, 15, 12), started_at=datetime(2026, 9, 15, 11, 31),
        )
        for user, task in zip(users, tasks, strict=True)
    ])
    await db_session.flush()

    team = await admin_client.get("/api/dashboard/team", params={"year": 2026, "month": 9})
    financial = await admin_client.get(
        "/api/dashboard/overview/financial", params={"year": 2026, "month": 9},
    )
    profitability = await admin_client.get(
        "/api/dashboard/profitability", params={"year": 2026, "month": 9},
    )
    assert team.status_code == financial.status_code == profitability.status_code == 200

    rows = {row["user_id"]: row for row in team.json()}
    assert rows[admin_user.id].get("hourly_rate") is None
    assert (rows[admin_user.id]["hours_this_month"], rows[admin_user.id]["cost"]) == (0.5, 19.33)
    assert rows[configured_rate.id]["hourly_rate"] == 30
    assert rows[configured_rate.id]["cost"] == 14.5
    assert rows[zero_rate.id]["hourly_rate"] == 0
    assert rows[zero_rate.id]["cost"] == 0

    assert financial.json()["total_cost"] == 33.83
    client_row = next(row for row in profitability.json()["clients"] if row["client_id"] == client.id)
    assert client_row["cost"] == 33.83
