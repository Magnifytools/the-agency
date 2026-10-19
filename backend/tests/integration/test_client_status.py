"""Estado explicado del cliente (cartera) contra Postgres real."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestStatus,
    GscDaily,
    GscSiteSync,
    Project,
    ProjectStatus,
    ReportCadence,
    Task,
    TaskStatus,
    TimeEntry,
    WeeklyDigest,
)
from backend.services.client_status import Viewer, portfolio

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 19)
ALL = Viewer(is_admin=True, tasks=True, digests=True, timesheet=True)
MEMBER = Viewer(is_admin=False, tasks=True, digests=True, timesheet=True)
NOTHING = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False)


async def _client(db, name="Cliente", **kw):
    client = Client(name=name, status=ClientStatus.active, **kw)
    db.add(client)
    await db.flush()
    return client


async def _row(db, client, viewer=ALL, today=TODAY):
    return (await portfolio(db, [client], viewer, today=today))[0]


async def _gsc(db, site, *, recent, previous, last=date(2026, 10, 16)):
    db.add(GscSiteSync(site_url=site, backfilled_at=datetime.now(UTC), last_data_date=last))
    start = last - timedelta(days=27)
    db.add(GscDaily(site_url=site, date=start, clicks=recent, impressions=recent * 10, position=5.0))
    db.add(GscDaily(site_url=site, date=start - timedelta(days=1), clicks=previous,
                    impressions=previous * 10, position=5.0))
    await db.flush()


async def test_nothing_measurable_is_no_data_never_ok(db_session):
    client = await _client(db_session)
    row = await _row(db_session, client, NOTHING)
    assert row["status"] == "no_data" and row["reasons"] == []


async def test_own_search_console_drop_asks_to_act(db_session):
    client = await _client(db_session, gsc_url="sc-domain:cae.es")
    await _gsc(db_session, "sc-domain:cae.es", recent=300, previous=1000)

    row = await _row(db_session, client)

    assert row["seo"]["source"] == "search_console"
    assert row["seo"]["trend"] == "drop_alert" and row["seo"]["change_pct"] == -70.0
    assert row["status"] == "act"
    assert row["reasons"][0] == "El tráfico de Google cae un 70 % en 28 días"


async def test_mild_dip_is_watch_and_small_base_never_alerts(db_session):
    dip = await _client(db_session, "Baja", gsc_url="sc-domain:baja.es")
    tiny = await _client(db_session, "Pequeño", gsc_url="sc-domain:tiny.es")
    await _gsc(db_session, "sc-domain:baja.es", recent=900, previous=1000)
    await _gsc(db_session, "sc-domain:tiny.es", recent=10, previous=60)  # -83 % pero base < 100

    assert (await _row(db_session, dip))["status"] == "watch"
    tiny_row = await _row(db_session, tiny)
    assert tiny_row["seo"]["trend"] == "down" and tiny_row["status"] == "watch"


async def test_engine_summary_is_the_fallback_without_own_property(db_session):
    client = await _client(db_session, engine_project_id=7, engine_summary_data={
        "clicks_30d": 1200, "clicks_previous_30d": 1000,
        "impressions_30d": 1, "impressions_previous_30d": 1, "as_of": "2026-10-18",
    })
    row = await _row(db_session, client)
    assert row["seo"]["source"] == "engine" and row["seo"]["trend"] == "up"
    assert row["status"] == "ok"


async def test_monthly_summary_due_then_late_then_ok(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.monthly))
    await db_session.flush()

    due = await _row(db_session, client, today=date(2026, 10, 3))   # septiembre cerrado hace 3 días
    late = await _row(db_session, client, today=date(2026, 10, 9))  # más de 5 días
    assert due["digest"]["state"] == "due" and due["status"] == "watch"
    assert "Toca enviar el resumen mensual" in due["reasons"]
    assert late["digest"]["state"] == "late" and late["status"] == "act"

    db_session.add(WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 1),
                                period_end=date(2026, 9, 30), status=DigestStatus.sent,
                                created_by=admin_user.id))
    await db_session.flush()
    sent = await _row(db_session, client, today=date(2026, 10, 9))
    assert sent["digest"]["state"] == "ok" and sent["status"] == "ok"


async def test_draft_summary_does_not_count_as_sent(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.monthly))
    db_session.add(WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 1),
                                period_end=date(2026, 9, 30), status=DigestStatus.draft,
                                created_by=admin_user.id))
    await db_session.flush()
    assert (await _row(db_session, client, today=date(2026, 10, 9)))["digest"]["state"] == "late"


async def test_overdue_tasks_and_late_followups(db_session):
    client = await _client(db_session)
    past = datetime(2026, 10, 10)
    db_session.add_all([
        Task(client_id=client.id, title=f"Vencida {i}", status=TaskStatus.pending, due_date=past)
        for i in range(2)
    ] + [
        Task(client_id=client.id, title="Hecha", status=TaskStatus.completed, due_date=past),
        Task(client_id=client.id, title="Espera", status=TaskStatus.waiting, waiting_for="cliente",
             follow_up_date=date(2026, 10, 15), due_date=past),
    ])
    await db_session.flush()

    row = await _row(db_session, client)

    # La tarea en espera no cuenta como vencida: el bloqueo es del cliente.
    assert row["tasks"] == {"overdue": 2, "waiting": 1, "followups_late": 1}
    assert row["status"] == "watch"
    assert row["reasons"] == ["2 tareas vencidas", "1 seguimiento con el cliente sin hacer"]

    db_session.add(Task(client_id=client.id, title="Vencida 3", status=TaskStatus.pending, due_date=past))
    await db_session.flush()
    assert (await _row(db_session, client))["status"] == "act"


async def test_fee_consumption_is_admin_only(db_session, admin_user):
    client = await _client(db_session, monthly_budget=100)
    db_session.add(Project(name="Retainer", client_id=client.id, status=ProjectStatus.active,
                           monthly_fee=200))
    task = Task(client_id=client.id, title="Trabajo", status=TaskStatus.in_progress)
    db_session.add(task)
    await db_session.flush()
    admin_user.hourly_rate = 60
    # 4 h × 60 €/h = 240 € sobre una cuota de 200 € (proyectos activos, no el presupuesto legacy).
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=240,
                             date=datetime(2026, 10, 14)))
    await db_session.flush()

    admin_row = await _row(db_session, client, ALL)
    member_row = await _row(db_session, client, MEMBER)

    assert admin_row["month"] == {"hours": 4.0, "fee": 200.0, "consumption_pct": 120.0}
    assert admin_row["status"] == "act"
    assert member_row["month"] == {"hours": 4.0}
    assert member_row["status"] == "ok"


async def test_portfolio_puts_what_needs_action_first(db_session):
    calm = await _client(db_session, "Alfa")
    burning = await _client(db_session, "Zeta")
    db_session.add_all([
        Task(client_id=burning.id, title=f"V{i}", status=TaskStatus.pending, due_date=datetime(2026, 10, 1))
        for i in range(3)
    ])
    await db_session.flush()

    rows = await portfolio(db_session, [calm, burning], ALL, today=TODAY)

    assert [r["client_name"] for r in rows] == ["Zeta", "Alfa"]
    assert [r["status"] for r in rows] == ["act", "ok"]


async def test_portfolio_endpoint_respects_viewer_permissions(member_client, admin_client, db_session):
    client = await _client(db_session, "Visible", monthly_budget=100)
    await db_session.commit()

    admin = (await admin_client.get("/api/clients/portfolio")).json()
    single = (await admin_client.get(f"/api/clients/{client.id}/status")).json()
    assert [r["client_id"] for r in admin] == [client.id]
    assert single["client_id"] == client.id and single["status"] == admin[0]["status"]

    member = await member_client.get("/api/clients/portfolio")
    if member.status_code == 200:
        for row in member.json():
            assert "fee" not in (row.get("month") or {})
    else:
        assert member.status_code == 403
