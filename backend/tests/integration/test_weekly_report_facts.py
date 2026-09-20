from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.db.models import (
    Client,
    ClientStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
)
from backend.services import weekly_report_service as service

pytestmark = pytest.mark.integration


def dt(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 -- ORM columns store naive UTC/civil values


async def _user(db, name: str, *, active=True, weekly=40.0, rate=50.0, qa=False):
    user = User(
        email=("qa-" if qa else "weekly-") + uuid4().hex + "@agency.local",
        hashed_password="x",
        full_name=name,
        role=UserRole.member,
        is_active=active,
        weekly_hours=weekly,
        hourly_rate=rate,
    )
    db.add(user)
    await db.flush()
    return user


async def test_operational_week_preserves_history_and_has_no_finance_query(
    db_session, monkeypatch
):
    monkeypatch.setattr(service, "business_today", lambda: date(2026, 10, 26))
    active = await _user(db_session, "Activa cero", weekly=0)
    inactive = await _user(db_session, "Antigua", active=False)
    inactive_empty = await _user(db_session, "Antigua sin actividad", active=False)
    qa = await _user(db_session, "QA Bot", qa=True)
    same_a = Client(name="Mismo nombre", status=ClientStatus.active)
    same_b = Client(name="Mismo nombre", status=ClientStatus.active)
    db_session.add_all([same_a, same_b])
    await db_session.flush()
    retired = Task(
        title="Retirada histórica",
        client_id=same_a.id,
        status=TaskStatus.completed,
        completed_at=dt(2026, 10, 25, 22, 30),
        retired_at=dt(2026, 10, 26),
        retired_reason="cerrada",
    )
    template = Task(
        title="Plantilla",
        client_id=same_a.id,
        status=TaskStatus.pending,
        is_recurring=True,
        due_date=dt(2026, 10, 27),
    )
    unknown = Task(
        title="Sin fecha histórica",
        client_id=same_b.id,
        status=TaskStatus.completed,
        completed_at=None,
    )
    outside = Task(
        title="Ya es lunes civil",
        client_id=same_b.id,
        status=TaskStatus.completed,
        completed_at=dt(2026, 10, 25, 23),
    )
    qa_completed = Task(
        title="Completada QA",
        assigned_to=qa.id,
        status=TaskStatus.completed,
        completed_at=dt(2026, 10, 22, 12),
    )
    qa_pending = Task(
        title="Pendiente QA",
        assigned_to=qa.id,
        status=TaskStatus.pending,
        due_date=dt(2026, 10, 27),
    )
    unassigned = Task(
        title="Pendiente sin asignar",
        status=TaskStatus.pending,
        due_date=dt(2026, 10, 27),
    )
    db_session.add_all(
        [retired, template, unknown, outside, qa_completed, qa_pending, unassigned]
    )
    await db_session.flush()
    db_session.add_all(
        [
            TimeEntry(
                user_id=active.id,
                task_id=retired.id,
                minutes=30,
                date=dt(2026, 10, 25, 22, 30),
                started_at=dt(2026, 10, 25, 22, 0),
            ),
            TimeEntry(
                user_id=inactive.id,
                task_id=unknown.id,
                minutes=40,
                date=dt(2026, 10, 20, 12),
            ),
            TimeEntry(
                user_id=active.id, task_id=None, minutes=20, date=dt(2026, 10, 21, 12)
            ),
            TimeEntry(
                user_id=qa.id,
                task_id=retired.id,
                minutes=999,
                date=dt(2026, 10, 21, 12),
            ),
            TimeEntry(
                user_id=active.id,
                task_id=outside.id,
                minutes=777,
                date=dt(2026, 10, 25, 23),
                started_at=dt(2026, 10, 25, 22, 59),
            ),
        ]
    )
    await db_session.flush()

    statements = []

    def capture(_conn, _cursor, statement, _params, _ctx, _many):
        statements.append(statement.lower())

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        facts = await service.collect_weekly_report_facts(
            db_session,
            period_start=date(2026, 10, 19),
            period_end=date(2026, 10, 25),
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", capture)

    assert facts.total_minutes == 90
    assert (
        next(row for row in facts.members if row.user_id == active.id).capacity_minutes
        == 0
    )
    assert (
        next(row for row in facts.members if row.user_id == inactive.id).minutes == 40
    )
    assert qa.id not in {row.user_id for row in facts.members}
    assert inactive_empty.id not in {row.user_id for row in facts.members}
    assert {(row.client_id, row.minutes) for row in facts.clients} == {
        (same_a.id, 30),
        (same_b.id, 40),
        (None, 20),
    }
    assert facts.completed_count == 1 and [row.title for row in facts.completed] == [
        "Retirada histórica"
    ]
    assert facts.pending_count == 1  # unassigned remains; QA/template are excluded
    assert facts.upcoming_count == 1
    assert [row.title for row in facts.upcoming] == ["Pendiente sin asignar"]
    assert facts.financial_clients == ()
    assert all(
        "hourly_rate" not in statement and "default_hourly_rate" not in statement
        for statement in statements
    )
    rendered = service.render_weekly_operational(facts)
    assert "90" not in rendered  # rendered as 1.5h, not raw minutes
    assert "€" not in rendered and "Coste" not in rendered
    assert "persona inactiva; actividad histórica" in rendered
    assert "Tiempo registrado en el período:** 1.5h" in rendered
    assert "Capacidad semanal actual del equipo activo:** 0h" in rendered
    assert "Activa cero: 0.8h (capacidad semanal actual configurada: 0h)" in rendered
    assert "🟥 Activa cero" not in rendered
    assert "Activa cero: 0.8h / 0h" not in rendered


def test_operational_render_separates_historical_time_from_current_capacity():
    facts = service.WeeklyReportFacts(
        period_start=date(2026, 9, 14),
        period_end=date(2026, 9, 20),
        snapshot_date=date(2026, 9, 21),
        completed_count=0,
        in_progress_count=0,
        pending_count=0,
        overdue_count=0,
        total_minutes=180,
        capacity_minutes=120,
        members=(
            service.WeeklyMember(1, "Activa", 60, 120, True),
            service.WeeklyMember(2, "Histórica", 120, None, False),
        ),
        clients=(),
        inactive_client_names=(),
        completed=(),
        in_progress=(),
        overdue=(),
        upcoming_count=0,
        upcoming=(),
    )

    rendered = service.render_weekly_operational(facts)

    assert "Tiempo registrado en el período:** 3h" in rendered
    assert "Capacidad semanal actual del equipo activo:** 2h" in rendered
    assert "Activa: 1h / 2h (50% de su capacidad semanal actual)" in rendered
    assert "Histórica: 2h (persona inactiva; actividad histórica)" in rendered
    assert "150%" not in rendered


async def test_totals_are_independent_of_samples_and_finance_is_explicit(
    db_session, monkeypatch
):
    monkeypatch.setattr(service, "business_today", lambda: date(2026, 9, 21))
    user = await _user(db_session, "Equipo", rate=60)
    client = Client(name="Volumen", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    db_session.add_all(
        [
            Task(
                title=f"Pendiente {i}",
                client_id=client.id,
                status=TaskStatus.pending,
                due_date=dt(2026, 9, 22 + (i % 5)),
            )
            for i in range(1005)
        ]
    )
    tracked = Task(
        title="Con tiempo", client_id=client.id, status=TaskStatus.in_progress
    )
    db_session.add(tracked)
    await db_session.flush()
    db_session.add(
        TimeEntry(
            user_id=user.id, task_id=tracked.id, minutes=120, date=dt(2026, 9, 16, 10)
        )
    )
    await db_session.flush()

    operational = await service.collect_weekly_report_facts(
        db_session, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20)
    )
    assert (
        operational.pending_count == 1005
        and operational.upcoming_count == 1005
        and len(operational.upcoming) == service.SAMPLE_LIMIT
    )
    assert "muestra 15 de 1005" in service.render_weekly_operational(operational)
    assert operational.financial_clients == ()

    financial = await service.collect_weekly_report_facts(
        db_session,
        period_start=date(2026, 9, 14),
        period_end=date(2026, 9, 20),
        include_financial=True,
    )
    assert [(row.client_id, row.cost) for row in financial.financial_clients] == [
        (client.id, 120.0)
    ]
    assert "120€" in service.render_weekly_financial(financial)


async def test_zero_time_week_still_lists_active_clients_without_activity(
    db_session, monkeypatch
):
    monkeypatch.setattr(service, "business_today", lambda: date(2026, 9, 21))
    await _user(db_session, "Sin horas")
    client = Client(name="Cliente sin actividad", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()

    facts = await service.collect_weekly_report_facts(
        db_session, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20)
    )

    assert facts.clients == ()
    assert facts.inactive_client_names == ("Cliente sin actividad",)
    assert "Sin actividad: Cliente sin actividad" in service.render_weekly_operational(
        facts
    )
