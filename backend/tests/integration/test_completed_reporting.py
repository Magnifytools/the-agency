"""Regression coverage for completed-task dates used by summaries and reports."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.db.models import Client, ClientStatus, Task, TaskStatus
from backend.services.digest_collector import collect_digest_data
from backend.services.weekly_report_service import generate_weekly_report


pytestmark = pytest.mark.integration


@pytest.fixture
async def reporting_client(db_session):
    client = Client(name=f"Reporting {uuid4().hex[:8]}", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    return client


async def test_digest_uses_completion_time_and_half_open_period(db_session, reporting_client):
    start = date(2026, 9, 1)
    end = date(2026, 9, 7)
    rows = [
        Task(
            title="Dentro aunque se editó después",
            client_id=reporting_client.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 2, 10),
            updated_at=datetime(2026, 9, 15, 10),
        ),
        Task(
            title="Fuera aunque se editó dentro",
            client_id=reporting_client.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 8, 31, 21, 59, 59),
            updated_at=datetime(2026, 9, 2, 10),
        ),
        Task(
            title="Histórica sin fecha",
            client_id=reporting_client.id,
            status=TaskStatus.completed,
            completed_at=None,
        ),
        Task(
            title="Último instante incluido",
            client_id=reporting_client.id,
            status=TaskStatus.completed,
            completed_at=datetime(2026, 9, 7, 21, 59, 59, 999999),
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    data = await collect_digest_data(db_session, reporting_client.id, start, end)

    assert {task["title"] for task in data["unassigned"]["completed_tasks"]} == {
        "Dentro aunque se editó después",
        "Último instante incluido",
    }


async def test_edit_reopen_and_recomplete_keep_completion_semantics(
    admin_client, db_session, reporting_client
):
    created = await admin_client.post("/api/tasks", json={
        "title": "Original",
        "client_id": reporting_client.id,
        "status": "completed",
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    first_completed_at = created.json()["completed_at"]

    edited = await admin_client.put(f"/api/tasks/{task_id}", json={"title": "Editada"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["completed_at"] == first_completed_at

    reopened = await admin_client.put(f"/api/tasks/{task_id}", json={"status": "pending"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["completed_at"] is None

    task = await db_session.get(Task, task_id)
    task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    await db_session.flush()
    recompleted = await admin_client.put(f"/api/tasks/{task_id}", json={"status": "completed"})
    assert recompleted.status_code == 200, recompleted.text
    assert recompleted.json()["completed_at"] > first_completed_at


async def test_weekly_report_counts_all_pending_beyond_display_limit(
    db_session, reporting_client
):
    db_session.add_all([
        Task(
            title=f"Pendiente {index:02d}",
            client_id=reporting_client.id,
            status=TaskStatus.pending,
            due_date=datetime.now() + timedelta(days=index + 1),
        )
        for index in range(18)
    ])
    await db_session.flush()

    report = await generate_weekly_report(db_session)

    assert "**Pendientes:** 18" in report
