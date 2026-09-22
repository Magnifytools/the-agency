"""Client detail projections must respect their source-module permissions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.db.models import Client, Task, TaskStatus, TimeEntry
from backend.services import client_advisor


pytestmark = pytest.mark.integration


async def test_client_only_reader_sees_client_without_task_or_time_data(
    db_session, make_member_client, admin_user,
):
    client = Client(name="Cliente privado")
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Tarea privada", client_id=client.id, estimated_minutes=45)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=30, notes="Nota privada"))
    await db_session.flush()

    reader = await make_member_client([("clients", True, False)])
    try:
        summary = await reader.get(f"/api/clients/{client.id}/summary")
        assert summary.status_code == 200, summary.text
        data = summary.json()
        assert data["client"]["name"] == "Cliente privado"
        assert data["tasks"] is None
        assert data["total_tasks"] is None
        assert data["total_estimated_minutes"] is None
        assert data["total_actual_minutes"] is None
        assert data["total_tracked_minutes"] is None
        assert (await reader.get(f"/api/clients/{client.id}/recent-time-entries")).status_code == 403
        assert (await reader.get(f"/api/clients/{client.id}/dashboard")).status_code in (403, 404)
        assert (await reader.get(f"/api/clients/{client.id}/what-if")).status_code in (403, 404)
    finally:
        await reader.aclose()


async def test_client_task_reader_sees_tasks_but_not_time_entries(
    db_session, make_member_client, admin_user,
):
    client = Client(name="Cliente tareas")
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Tarea visible", client_id=client.id, estimated_minutes=45)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=30, notes="Nota privada"))
    await db_session.flush()

    reader = await make_member_client([("clients", True, False), ("tasks", True, False)])
    try:
        summary = await reader.get(f"/api/clients/{client.id}/summary")
        assert summary.status_code == 200, summary.text
        data = summary.json()
        assert [row["title"] for row in data["tasks"]] == ["Tarea visible"]
        assert data["total_tasks"] == 1
        assert data["total_tracked_minutes"] is None
        assert (await reader.get(f"/api/clients/{client.id}/recent-time-entries")).status_code == 403
    finally:
        await reader.aclose()


async def test_client_time_projection_requires_tasks_and_timesheet(
    db_session, make_member_client, admin_user,
):
    client = Client(name="Cliente tiempo")
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Tarea tiempo", client_id=client.id)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=30, notes="Nota permitida"))
    await db_session.flush()

    time_only = await make_member_client([("clients", True, False), ("timesheet", True, False)])
    full = await make_member_client([
        ("clients", True, False), ("tasks", True, False), ("timesheet", True, False),
    ])
    try:
        assert (await time_only.get(f"/api/clients/{client.id}/recent-time-entries")).status_code == 403
        summary = await full.get(f"/api/clients/{client.id}/summary")
        assert summary.status_code == 200, summary.text
        assert summary.json()["total_tracked_minutes"] == 30
        entries = await full.get(f"/api/clients/{client.id}/recent-time-entries")
        assert entries.status_code == 200, entries.text
        assert entries.json()[0]["notes"] == "Nota permitida"
    finally:
        await time_only.aclose()
        await full.aclose()


async def test_client_activity_filters_task_events_without_tasks_read(
    db_session, make_member_client,
):
    client = Client(name="Cliente actividad privada")
    db_session.add(client)
    await db_session.flush()
    db_session.add(Task(
        title="Título privado", description="Detalle privado", client_id=client.id,
        status=TaskStatus.completed, completed_at=datetime(2026, 9, 20, 12),
    ))
    await db_session.flush()

    client_only = await make_member_client([("clients", True, False)])
    with_tasks = await make_member_client([("clients", True, False), ("tasks", True, False)])
    try:
        private_feed = await client_only.get(f"/api/clients/{client.id}/activity")
        assert private_feed.status_code == 200, private_feed.text
        assert private_feed.json() == []

        allowed_feed = await with_tasks.get(f"/api/clients/{client.id}/activity")
        assert allowed_feed.status_code == 200, allowed_feed.text
        assert {row["type"] for row in allowed_feed.json()} == {"task_created", "task_completed"}
        assert all(row["description"] == "Título privado" for row in allowed_feed.json())
    finally:
        await client_only.aclose()
        await with_tasks.aclose()


async def test_client_advice_omits_unreadable_sources_before_ai_call(
    db_session, make_member_client, admin_user, monkeypatch,
):
    client = Client(name="Cliente IA", monthly_budget=500)
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Tarea secreta", client_id=client.id, status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=90))
    await db_session.flush()

    prompts = []

    async def capture(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return SimpleNamespace()

    monkeypatch.setattr(client_advisor, "get_anthropic_client", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=capture)),
    ))
    monkeypatch.setattr(client_advisor, "parse_claude_json", lambda _: {"recommendations": []})

    client_writer = await make_member_client([("clients", True, True)])
    task_reader = await make_member_client([("clients", True, True), ("tasks", True, False)])
    try:
        basic = await client_writer.post(f"/api/clients/{client.id}/ai-advice")
        assert basic.status_code == 200, basic.text
        assert "Tareas:" not in prompts[-1]
        assert "Horas este mes:" not in prompts[-1]
        assert "Presupuesto mensual:" not in prompts[-1]
        assert "Total comunicaciones:" not in prompts[-1]

        task_only = await task_reader.post(f"/api/clients/{client.id}/ai-advice")
        assert task_only.status_code == 200, task_only.text
        assert "Tareas:" in prompts[-1]
        assert "Horas este mes:" not in prompts[-1]
    finally:
        await client_writer.aclose()
        await task_reader.aclose()
