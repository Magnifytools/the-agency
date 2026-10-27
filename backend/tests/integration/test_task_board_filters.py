"""Filtros de la lista de tareas que usan el tablero y la semana."""

from datetime import date, datetime
from uuid import uuid4

import pytest

from backend.db.models import Client, ClientStatus, Task, TaskStatus


pytestmark = pytest.mark.integration


@pytest.fixture
async def board_client(db_session):
    client = Client(name=f"Tablero {uuid4().hex[:8]}", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    return client


async def _titles(admin_client, client_id, **params):
    response = await admin_client.get("/api/tasks", params={"client_id": client_id, **params})
    assert response.status_code == 200, response.text
    return {item["title"] for item in response.json()["items"]}


async def test_completed_from_uses_the_civil_day_in_madrid(admin_client, db_session, board_client):
    db_session.add_all([
        # 22:00 UTC del 19 oct = 00:00 del 20 oct en Madrid (CEST).
        Task(title="Primer instante", client_id=board_client.id, status=TaskStatus.completed,
             completed_at=datetime(2026, 10, 19, 22, 0)),
        Task(title="Víspera", client_id=board_client.id, status=TaskStatus.completed,
             completed_at=datetime(2026, 10, 19, 21, 59, 59)),
        Task(title="Sin fecha de cierre", client_id=board_client.id, status=TaskStatus.completed),
    ])
    await db_session.flush()

    assert await _titles(admin_client, board_client.id, status="completed", completed_from="2026-10-20") == {
        "Primer instante",
    }


async def test_completed_from_rejects_a_malformed_date(admin_client, board_client):
    response = await admin_client.get("/api/tasks", params={"completed_from": "20-10-2026"})
    assert response.status_code == 422


async def test_unscheduled_keeps_only_tasks_without_planned_day(admin_client, db_session, board_client):
    db_session.add_all([
        Task(title="Sin planificar", client_id=board_client.id, status=TaskStatus.pending),
        Task(title="Con fecha límite pero sin plan", client_id=board_client.id, status=TaskStatus.backlog,
             due_date=datetime(2026, 11, 3)),
        Task(title="Planificada", client_id=board_client.id, status=TaskStatus.pending,
             scheduled_date=date(2026, 10, 28)),
    ])
    await db_session.flush()

    assert await _titles(admin_client, board_client.id, status="pending,backlog", unscheduled="true") == {
        "Sin planificar", "Con fecha límite pero sin plan",
    }
