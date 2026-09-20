from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.db.models import (
    AuditLog,
    ChangeLog,
    Client,
    CommandReceipt,
    DailyUpdate,
    Delivery,
    Notification,
    Project,
    Task,
    TaskStatus,
)
from backend.services.operational_usage import collect_operational_usage
from backend.services.temporal import utc_now_naive

pytestmark = pytest.mark.asyncio


async def test_operational_metrics_keep_populations_and_denominators_explicit(
    admin_client, admin_user, db_session,
):
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc).replace(tzinfo=None)
    client = Client(name="Metrics client", status="active")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Metrics project", status="active", client_id=client.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add_all([
        Task(title="Context", project_id=project.id, status=TaskStatus.pending,
             scheduled_date=date(2026, 9, 22)),
        Task(title="Internal waiting", status=TaskStatus.waiting),
        Task(title="Unplanned", status=TaskStatus.pending),
        Task(title="Template", status=TaskStatus.pending, is_recurring=True),
        Task(title="Retired", status=TaskStatus.pending, retired_at=now,
             retired_reason="No longer operational"),
        Task(title="Done", status=TaskStatus.completed),
    ])
    db_session.add_all([
        Notification(user_id=admin_user.id, type="x", title="active", incident_state="active"),
        Notification(user_id=admin_user.id, type="x", title="snoozed", incident_state="snoozed"),
        Notification(user_id=admin_user.id, type="x", title="dismissed", incident_state="dismissed"),
        Notification(user_id=admin_user.id, type="x", title="resolved", incident_state="resolved",
                     incident_detected_at=now - timedelta(days=90), incident_resolved_at=now - timedelta(days=2)),
    ])
    db_session.add_all([
        DailyUpdate(user_id=admin_user.id, date=date(2026, 9, 19), raw_text="private one", created_at=now - timedelta(days=2)),
        DailyUpdate(user_id=admin_user.id, date=date(2026, 9, 20), raw_text="private two", created_at=now - timedelta(days=1)),
    ])
    journal = ChangeLog(user_id=admin_user.id, entity_type="task", entity_id=1,
                        action="update", label="private", operations=[], undone_at=now)
    db_session.add(journal)
    await db_session.flush()
    statuses = ["executed", "failed", "needs_input", "needs_review"]
    for index, status in enumerate(statuses):
        db_session.add(CommandReceipt(
            id=str(uuid4()), user_id=admin_user.id, request_key=f"operational-command-{index:02d}",
            request_hash="a" * 64, channel="app" if index < 2 else "extension",
            raw_text="private command", status=status, revision=1, step_replays={},
            change_log_id=journal.id if index == 0 else None, created_at=now - timedelta(days=1),
        ))
    for index, status in enumerate(("sent", "failed", "uncertain", "expired", "cancelled", "pending", "sending")):
        db_session.add(Delivery(
            id=str(uuid4()), dedupe_key=f"operational-delivery-{index}", actor_id=admin_user.id,
            source_kind="daily", source_id=index + 1, source_version="v1",
            destination_key="private", payload={"content": "secret"}, status=status,
            available_at=now, expires_at=now + timedelta(days=1), created_at=now - timedelta(days=1),
        ))
    await db_session.flush()

    data = await collect_operational_usage(db_session, days=30, now=now)
    assert data["work_context"] == {"total": 3, "with_project": 1, "without_project": 2, "coverage_percent": 33.3}
    assert data["work_planning"] == {"total": 3, "planned_or_waiting": 2, "unplanned": 1, "coverage_percent": 66.7}
    assert data["incidents"] == {"active": 1, "snoozed": 1, "dismissed": 1, "resolved_in_window": 1}
    assert data["dailys"] == {"updates": 2, "authors": 1, "user_days": 2}
    assert data["commands"]["success_percent"] == 50.0
    assert data["commands"]["undone"] == 1
    assert data["commands"]["by_channel"] == {"app": 2, "extension": 2, "unknown": 0}
    assert data["deliveries"]["terminal_total"] == 4
    assert data["deliveries"]["confirmation_percent"] == 25.0

    response = await admin_client.get("/api/admin/usage/operational?days=30")
    assert response.status_code == 200
    rendered = response.text
    assert all(secret not in rendered for secret in ("private one", "private command", "secret"))


async def test_operational_zero_denominators_are_unknown_and_endpoint_is_admin_only(
    member_client, db_session,
):
    old = datetime(2000, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    data = await collect_operational_usage(db_session, days=1, now=old)
    assert data["work_context"]["coverage_percent"] is None
    assert data["work_planning"]["coverage_percent"] is None
    assert data["commands"]["success_percent"] is None
    assert data["deliveries"]["confirmation_percent"] is None
    assert (await member_client.get("/api/admin/usage/operational")).status_code == 403


async def test_usage_origin_groups_null_history_and_filters_routes(admin_client, db_session):
    now = utc_now_naive()
    db_session.add_all([
        AuditLog(user_id=admin_client.test_user.id, method="GET", route_template="/api/tasks",
                 status_code=200, duration_ms=10, client_origin="web", created_at=now),
        AuditLog(user_id=admin_client.test_user.id, method="GET", route_template="/api/tasks",
                 status_code=200, duration_ms=20, client_origin="extension", created_at=now),
        AuditLog(user_id=admin_client.test_user.id, method="GET", route_template="/api/tasks",
                 status_code=200, duration_ms=30, client_origin=None, created_at=now),
        AuditLog(user_id=admin_client.test_user.id, action="legacy_action",
                 entity_type="task", entity_id=1, created_at=now),
    ])
    await db_session.flush()
    grouped = await admin_client.get("/api/admin/usage/origins")
    assert grouped.status_code == 200
    assert grouped.json() == [
        {"origin": "extension", "hits": 1},
        {"origin": "unknown", "hits": 1},
        {"origin": "web", "hits": 1},
    ]
    filtered = await admin_client.get("/api/admin/usage/top-routes?origin=extension")
    assert filtered.status_code == 200
    assert filtered.json()[0]["hits"] == 1
    users = await admin_client.get("/api/admin/usage/by-user")
    assert sum(row["hits"] for row in users.json()) == 3
    days = await admin_client.get("/api/admin/usage/daily")
    assert sum(row["hits"] for row in days.json()) == 3
    assert (await admin_client.get("/api/admin/usage/top-routes?origin=assistant")).status_code == 422


async def test_operational_metrics_use_a_constant_six_selects(db_session, engine):
    selects = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        fixed = datetime(2026, 9, 21, 12, tzinfo=timezone.utc).replace(tzinfo=None)
        await collect_operational_usage(db_session, days=30, now=fixed)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert len(selects) == 6


async def test_declared_origin_header_is_allowed_by_cors(admin_client):
    response = await admin_client.options("/api/tasks", headers={
        "Origin": "http://localhost:5177",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Agency-Client",
    })
    assert response.status_code == 200
    assert "x-agency-client" in response.headers["access-control-allow-headers"].lower()
