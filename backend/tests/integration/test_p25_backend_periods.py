"""P25 civil-date and trustworthy completion regressions."""
from datetime import date, datetime

import pytest

from backend.api.routes import tasks as tasks_route
from backend.db.models import Client, Task, TaskStatus
from backend.services.daily_reminders import generate_evening_recap

pytestmark = pytest.mark.integration


def dt(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 -- application columns store naive UTC/civil values


async def test_overdue_filter_uses_madrid_business_date(
    admin_client, admin_user, db_session, monkeypatch
):
    # The route must use the injected business day, not the process-local date.
    # The UTC/Madrid boundary itself is covered by test_temporal_contract.py.
    monkeypatch.setattr(tasks_route, "business_today", lambda: date(2026, 9, 22))
    yesterday = Task(
        title="Venció en el día UTC anterior",
        assigned_to=admin_user.id,
        status=TaskStatus.pending,
        due_date=dt(2026, 9, 21, 12),
    )
    today = Task(
        title="Vence hoy en Madrid",
        assigned_to=admin_user.id,
        status=TaskStatus.pending,
        due_date=dt(2026, 9, 22, 12),
    )
    completed = Task(
        title="Completada no vuelve a deuda",
        assigned_to=admin_user.id,
        status=TaskStatus.completed,
        due_date=dt(2026, 9, 21, 12),
        completed_at=dt(2026, 9, 20, 18),
    )
    db_session.add_all([yesterday, today, completed])
    await db_session.flush()

    response = await admin_client.get("/api/tasks", params={"overdue": "true"})
    assert response.status_code == 200, response.text
    titles = {item["title"] for item in response.json()["items"]}
    assert "Venció en el día UTC anterior" in titles
    assert "Vence hoy en Madrid" not in titles
    assert "Completada no vuelve a deuda" not in titles


async def test_client_activity_dates_completion_from_completed_at_and_omits_unknown(
    admin_client, admin_user, db_session
):
    client = Client(name="Cliente actividad fiable")
    db_session.add(client)
    await db_session.flush()
    reliable = Task(
        title="Finalización fiable",
        client_id=client.id,
        assigned_to=admin_user.id,
        status=TaskStatus.completed,
        completed_at=dt(2026, 9, 18, 9, 15),
        updated_at=dt(2026, 9, 20, 17, 45),
    )
    unknown = Task(
        title="Finalización sin fecha",
        client_id=client.id,
        assigned_to=admin_user.id,
        status=TaskStatus.completed,
        completed_at=None,
        updated_at=dt(2026, 9, 20, 18),
    )
    db_session.add_all([reliable, unknown])
    await db_session.flush()

    response = await admin_client.get(f"/api/clients/{client.id}/activity")
    assert response.status_code == 200, response.text
    completions = [row for row in response.json() if row["type"] == "task_completed"]
    assert [(row["description"], row["timestamp"]) for row in completions] == [
        ("Finalización fiable", "2026-09-18T09:15:00")
    ]


async def test_evening_recap_explains_completion_date_scope(db_session, admin_user):
    message = await generate_evening_recap(
        db_session, admin_user, date(2026, 9, 18)
    )
    assert "fecha de finalización registrada" in message
