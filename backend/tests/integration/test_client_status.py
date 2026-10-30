"""Estado explicado del cliente (cartera) contra Postgres real."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestStatus,
    ExternalDeliveryAction,
    GscDaily,
    GscSiteSync,
    Project,
    ProjectStatus,
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


async def test_engine_summary_is_no_longer_a_fallback(db_session):
    """The Engine está congelado (21 oct 2026): sin propiedad propia no hay señal de tráfico."""
    client = await _client(db_session, engine_project_id=7, engine_summary_data={
        "clicks_30d": 100, "clicks_previous_30d": 1000,
        "impressions_30d": 1, "impressions_previous_30d": 1, "as_of": "2026-10-18",
    })
    row = await _row(db_session, client, NOTHING)
    assert row["seo"] is None
    assert row["status"] == "no_data" and row["reasons"] == []


async def test_property_typed_without_trailing_slash_still_matches(db_session):
    client = await _client(db_session, gsc_url="https://sube.es")
    await _gsc(db_session, "https://sube.es/", recent=1200, previous=1000)
    row = await _row(db_session, client, NOTHING)
    assert row["seo"]["trend"] == "up" and row["status"] == "ok"


async def test_monthly_summary_due_then_late_then_ok(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, monthly_enabled=True))
    await db_session.flush()

    due = await _row(db_session, client, today=date(2026, 10, 3))   # septiembre cerrado hace 3 días
    late = await _row(db_session, client, today=date(2026, 10, 9))  # más de 5 días
    assert due["digest"]["state"] == "due" and due["status"] == "watch"
    assert "Toca enviar el informe mensual" in due["reasons"]
    assert late["digest"]["state"] == "late" and late["status"] == "act"
    assert "El informe mensual está atrasado" in late["reasons"]

    # La etiqueta "sent" sin entrega externa confirmada no cuenta.
    db_session.add(WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 1),
                                period_end=date(2026, 9, 30), status=DigestStatus.sent,
                                created_by=admin_user.id))
    await db_session.flush()
    assert (await _row(db_session, client, today=date(2026, 10, 9)))["digest"]["state"] == "late"

    await _delivered(db_session, client, admin_user, date(2026, 9, 1), date(2026, 9, 30),
                     ExternalDeliveryAction.confirmed)
    sent = await _row(db_session, client, today=date(2026, 10, 9))
    assert sent["digest"]["state"] == "ok" and sent["status"] == "ok"


async def test_both_cadences_give_one_signal_each_and_digest_is_the_worst(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, weekly_enabled=True, monthly_enabled=True))
    await db_session.flush()
    # Septiembre entregado; la semana del 12 al 18 de octubre, no.
    await _delivered(db_session, client, admin_user, date(2026, 9, 1), date(2026, 9, 30),
                     ExternalDeliveryAction.confirmed)
    # Una entrega semanal confirmada no cuenta como mensual (ni al revés).
    await _delivered(db_session, client, admin_user, date(2026, 9, 28), date(2026, 10, 4),
                     ExternalDeliveryAction.confirmed)

    row = await _row(db_session, client, today=date(2026, 10, 24))  # semana 12-18 + 5 días

    assert [(d["cadence"], d["state"]) for d in row["digests"]] == [("monthly", "ok"), ("weekly", "late")]
    assert row["digests"][1]["last_sent_period_end"] == "2026-10-04"
    assert row["digest"]["cadence"] == "weekly" and row["digest"]["state"] == "late"
    assert "El seguimiento semanal está atrasado" in row["reasons"]
    assert row["status"] == "act"

    due = await _row(db_session, client, today=date(2026, 10, 19))
    assert [(d["cadence"], d["state"]) for d in due["digests"]] == [("monthly", "ok"), ("weekly", "due")]
    assert "Toca enviar el seguimiento semanal" in due["reasons"]


async def test_policy_with_both_cadences_off_has_no_digest_signal(db_session):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id))
    await db_session.flush()
    row = await _row(db_session, client)
    assert row["digests"] == [] and row["digest"] is None


async def test_draft_summary_does_not_count_as_sent(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, monthly_enabled=True))
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
    # Lo listo para entregar sólo viaja en la ficha, no en la cartera.
    assert single["ready"]["count"] == 0 and admin[0]["ready"] is None

    member = await member_client.get("/api/clients/portfolio")
    if member.status_code == 200:
        for row in member.json():
            assert "fee" not in (row.get("month") or {})
    else:
        assert member.status_code == 403


# ── Listo para entregar ─────────────────────────────────────────────


async def _delivered(db, client, actor, start, end, *actions):
    digest = WeeklyDigest(client_id=client.id, period_start=start, period_end=end,
                          status=DigestStatus.draft, created_by=actor.id)
    db.add(digest)
    await db.flush()
    for minute, action in enumerate(actions):
        db.add(DigestExternalDeliveryEvent(
            digest_id=digest.id, action=action, actor_id=actor.id, request_key=uuid4().hex,
            request_hash="a" * 64, created_at=datetime(2026, 10, 2, 9, minute),
        ))
    await db.flush()
    return digest


def _done(client, title, completed_at, **kw):
    return Task(client_id=client.id, title=title, status=TaskStatus.completed,
                completed_at=completed_at, **kw)


async def _ready(db, client, viewer=ALL, today=TODAY):
    return (await portfolio(db, [client], viewer, today=today, detail=True))[0]["ready"]


async def test_ready_lists_completed_work_of_the_period_due(db_session):
    client = await _client(db_session)
    db_session.add_all([
        _done(client, "Auditoría", datetime(2026, 9, 10, 10)),
        _done(client, "Informe enlaces", datetime(2026, 10, 14, 10)),
        _done(client, "De agosto", datetime(2026, 8, 31, 10)),  # antes del periodo que toca
        Task(client_id=client.id, title="Por revisar", status=TaskStatus.in_review),
        _done(client, "Retirada", datetime(2026, 10, 1, 10), retired_at=datetime(2026, 10, 2), retired_reason="duplicada"),
        _done(client, "Plantilla", datetime(2026, 10, 1, 10), is_recurring=True),
    ])
    await db_session.flush()

    ready = await _ready(db_session, client)

    # Sin política: ciclo mensual, desde el 1 del mes cerrado.
    assert ready["since"] == "2026-09-01"
    assert ready["count"] == 2
    assert [t["title"] for t in ready["items"]] == ["Informe enlaces", "Auditoría"]
    assert ready["items"][0]["completed_on"] == "2026-10-14"


async def test_confirmed_delivery_moves_the_start_and_revocation_undoes_it(db_session, admin_user):
    client = await _client(db_session)
    db_session.add(ClientReportPolicy(client_id=client.id, monthly_enabled=True))
    db_session.add_all([
        _done(client, "Entregada", datetime(2026, 9, 20, 10)),
        _done(client, "Nueva", datetime(2026, 10, 5, 10)),
    ])
    await db_session.flush()
    revoked = await _delivered(db_session, client, admin_user, date(2026, 9, 1), date(2026, 9, 30),
                               ExternalDeliveryAction.confirmed, ExternalDeliveryAction.revoked)
    # Una etiqueta "sent" sin evento no es una entrega.
    db_session.add(WeeklyDigest(client_id=client.id, period_start=date(2026, 9, 1),
                                period_end=date(2026, 9, 30), status=DigestStatus.sent,
                                created_by=admin_user.id))
    await db_session.flush()
    assert (await _ready(db_session, client))["count"] == 2

    db_session.add(DigestExternalDeliveryEvent(
        digest_id=revoked.id, action=ExternalDeliveryAction.confirmed, actor_id=admin_user.id,
        request_key=uuid4().hex, request_hash="a" * 64, created_at=datetime(2026, 10, 3, 9),
    ))
    await db_session.flush()
    ready = await _ready(db_session, client)
    assert ready["since"] == "2026-10-01"
    assert [t["title"] for t in ready["items"]] == ["Nueva"]


async def test_ready_day_boundary_is_madrid_civil_day(db_session, admin_user):
    client = await _client(db_session)
    await _delivered(db_session, client, admin_user, date(2026, 9, 1), date(2026, 9, 30),
                     ExternalDeliveryAction.confirmed)
    db_session.add_all([
        _done(client, "30 sept. en Madrid", datetime(2026, 9, 30, 21, 30)),  # 23:30 en Madrid
        _done(client, "1 oct. en Madrid", datetime(2026, 9, 30, 22, 30)),    # 00:30 en Madrid
    ])
    await db_session.flush()

    ready = await _ready(db_session, client)
    assert [t["title"] for t in ready["items"]] == ["1 oct. en Madrid"]
    assert ready["items"][0]["completed_on"] == "2026-10-01"


async def test_ready_needs_tasks_and_digests_and_is_not_in_the_portfolio(db_session):
    client = await _client(db_session)
    db_session.add(_done(client, "Hecha", datetime(2026, 10, 14, 10)))
    await db_session.flush()

    no_digests = Viewer(is_admin=False, tasks=True, digests=False, timesheet=True)
    assert await _ready(db_session, client, no_digests) is None
    assert (await _row(db_session, client))["ready"] is None
    assert (await _ready(db_session, client))["count"] == 1


async def test_ready_uses_the_week_only_when_the_weekly_is_the_only_cadence(db_session):
    weekly = await _client(db_session, "Semanal")
    both = await _client(db_session, "Ambas")
    db_session.add_all([
        ClientReportPolicy(client_id=weekly.id, weekly_enabled=True),
        ClientReportPolicy(client_id=both.id, weekly_enabled=True, monthly_enabled=True),
    ])
    await db_session.flush()
    assert (await _ready(db_session, weekly))["since"] == "2026-10-12"
    # Con las dos cadencias manda el informe mensual.
    assert (await _ready(db_session, both))["since"] == "2026-09-01"
