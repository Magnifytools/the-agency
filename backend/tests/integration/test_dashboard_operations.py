"""Fila "Operación" del dashboard contra Postgres real.

Cada cifra sale del servicio que ya decide su regla en otra pantalla; aquí se
comprueba que el número es el mismo y que sólo lo ve quien puede leer su fuente.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    WeeklyDigest,
)
from backend.services.operations_summary import operations_summary

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 20, 10)  # noqa: DTZ001 - UTC, 20 oct en Madrid
SEPT = (date(2026, 9, 1), date(2026, 9, 30))


async def _client(db, name, **kw):
    client = Client(name=name, status=kw.pop("status", ClientStatus.active), **kw)
    db.add(client)
    await db.flush()
    return client


async def _project(db, client, name, **kw):
    project = Project(name=name, client_id=client.id, status=kw.pop("status", ProjectStatus.active), **kw)
    db.add(project)
    await db.flush()
    return project


async def test_recurring_fee_sums_active_projects_of_active_external_clients(db_session, admin_user):
    acme = await _client(db_session, "Acme")
    beta = await _client(db_session, "Beta")
    internal = await _client(db_session, "Magnify", is_internal=True)
    gone = await _client(db_session, "Antiguo", status=ClientStatus.finished)
    await _project(db_session, acme, "SEO", monthly_fee=1500)
    await _project(db_session, acme, "Contenidos", monthly_fee=500)
    await _project(db_session, acme, "Pausado", monthly_fee=900, status=ProjectStatus.on_hold)
    await _project(db_session, beta, "Auditoría", monthly_fee=None)
    await _project(db_session, internal, "Web propia", monthly_fee=300)
    await _project(db_session, gone, "Retainer", monthly_fee=700)

    ops = await operations_summary(db_session, admin_user, now=NOW)

    # Sólo Acme factura: Beta no tiene cuota, el pausado no cuenta, el interno
    # y el cliente terminado quedan fuera.
    assert ops["recurring_fee"] == {"total": 2000.0, "clients": 1}


async def test_projects_past_closing_or_over_monthly_hours(db_session, admin_user):
    client = await _client(db_session, "Acme")
    late = await _project(db_session, client, "Migración", target_end_date=datetime(2026, 10, 8))
    planning_late = await _project(db_session, client, "Rediseño", status=ProjectStatus.planning,
                                   target_end_date=datetime(2026, 10, 19))
    await _project(db_session, client, "Cerrado", status=ProjectStatus.completed,
                   target_end_date=datetime(2026, 9, 1))
    await _project(db_session, client, "En plazo", target_end_date=datetime(2026, 11, 30))
    # Retainer: budget_hours es su techo mensual (effective_budgets).
    over = await _project(db_session, client, "Retainer", is_recurring=True, budget_hours=10)
    under = await _project(db_session, client, "Retainer holgado", is_recurring=True, budget_hours=20)
    for project, minutes in ((over, 13 * 60), (under, 5 * 60)):
        task = Task(title=f"Trabajo {project.name}", client_id=client.id, project_id=project.id,
                    status=TaskStatus.in_progress)
        db_session.add(task)
        await db_session.flush()
        db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=minutes, date=datetime(2026, 10, 14)))
    # Horas del mes anterior: no cuentan para el mes en curso.
    task = Task(title="Septiembre", client_id=client.id, project_id=under.id, status=TaskStatus.completed)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=30 * 60, date=datetime(2026, 9, 20)))
    await db_session.flush()

    projects = (await operations_summary(db_session, admin_user, now=NOW))["projects_at_risk"]

    assert projects["count"] == 3
    # Primero los cierres vencidos (el más antiguo arriba), luego las horas.
    assert projects["items"] == [
        {"id": late.id, "name": "Migración", "reasons": ["Cierre vencido hace 12 días"]},
        {"id": planning_late.id, "name": "Rediseño", "reasons": ["Cierre vencido hace 1 día"]},
        {"id": over.id, "name": "Retainer", "reasons": ["Horas del mes al 130 %"]},
    ]


async def test_clients_to_act_come_from_the_portfolio_status(db_session, admin_user):
    burning = await _client(db_session, "Arde")
    await _client(db_session, "Tranquilo")
    db_session.add_all([
        Task(client_id=burning.id, title=f"Vencida {i}", status=TaskStatus.pending, due_date=datetime(2026, 10, 1))
        for i in range(3)
    ])
    await db_session.flush()

    clients = (await operations_summary(db_session, admin_user, now=NOW))["clients_to_act"]

    assert clients == {"count": 1, "items": [{"id": burning.id, "name": "Arde", "reason": "3 tareas vencidas"}]}


async def test_digests_unsent_follow_the_confirmed_delivery_rule(db_session, admin_user):
    pending = await _client(db_session, "Sin entregar")
    delivered = await _client(db_session, "Entregado")
    weekly = await _client(db_session, "Semanal")
    both = await _client(db_session, "Mensual y semanal")
    for client, flags in ((pending, {"monthly_enabled": True}), (delivered, {"monthly_enabled": True}),
                          (weekly, {"weekly_enabled": True}),
                          (both, {"monthly_enabled": True, "weekly_enabled": True})):
        db_session.add(ClientReportPolicy(client_id=client.id, **flags))
    await db_session.flush()
    digest = WeeklyDigest(client_id=delivered.id, period_start=SEPT[0], period_end=SEPT[1], created_by=admin_user.id)
    draft = WeeklyDigest(client_id=pending.id, period_start=SEPT[0], period_end=SEPT[1], created_by=admin_user.id)
    db_session.add_all([digest, draft])
    await db_session.flush()
    db_session.add(DigestExternalDeliveryEvent(
        digest_id=digest.id, action=ExternalDeliveryAction.confirmed, actor_id=admin_user.id,
        request_key=uuid4().hex, request_hash="a" * 64,
    ))
    await db_session.flush()

    digests = (await operations_summary(db_session, admin_user, now=NOW))["digests_unsent"]

    # Un borrador sin entrega confirmada sigue pendiente; el sólo semanal no
    # entra y el que tiene las dos cadencias cuenta por su informe mensual.
    assert digests == {
        "count": 2, "month": "septiembre de 2026", "period_start": "2026-09-01", "period_end": "2026-09-30",
        "items": [{"id": pending.id, "name": "Sin entregar"}, {"id": both.id, "name": "Mensual y semanal"}],
    }


async def test_each_indicator_needs_its_source_and_money_needs_admin(db_session, make_member_client):
    client = await _client(db_session, "Acme")
    over = await _project(db_session, client, "Retainer", is_recurring=True, budget_hours=1,
                          monthly_fee=1000, target_end_date=datetime(2026, 1, 1))
    task = Task(title="Trabajo", client_id=client.id, project_id=over.id, status=TaskStatus.in_progress)
    db_session.add(task)
    await db_session.flush()

    http = await make_member_client([("dashboard", True, False), ("projects", True, False)])
    db_session.add(TimeEntry(task_id=task.id, user_id=http.test_user.id, minutes=600, date=datetime.now()))  # noqa: DTZ005
    await db_session.flush()

    response = await http.get("/api/dashboard/operations")

    assert response.status_code == 200
    body = response.json()
    # Sin clientes ni resúmenes no hay cifra; la cuota es sólo admin.
    assert body["recurring_fee"] is None
    assert body["clients_to_act"] is None
    assert body["digests_unsent"] is None
    # Sin timesheet sólo se mide el cierre, no las horas.
    [item] = body["projects_at_risk"]["items"]
    assert item["id"] == over.id and len(item["reasons"]) == 1
    assert item["reasons"][0].startswith("Cierre vencido")


async def test_admin_gets_every_indicator_over_http(admin_client):
    response = await admin_client.get("/api/dashboard/operations")

    assert response.status_code == 200
    assert set(response.json()) == {"recurring_fee", "projects_at_risk", "clients_to_act", "digests_unsent"}
    assert all(value is not None for value in response.json().values())


async def test_without_dashboard_access_the_row_is_forbidden(member_client):
    assert (await member_client.get("/api/dashboard/operations")).status_code == 403
