"""Client AI advice must describe Madrid civil dates and time-entry periods."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.db.models import Client, Task, TaskStatus, TimeEntry
from backend.services import client_advisor
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration


def _naive(*parts: int) -> datetime:
    """The legacy DateTime columns intentionally store naive values."""
    return datetime(*parts)  # noqa: DTZ001


async def test_advice_prompt_uses_madrid_today_and_month_boundaries(
    db_session, admin_user, monkeypatch
):
    client = Client(name="Cliente de frontera")
    db_session.add(client)
    await db_session.flush()

    rollover = datetime(2026, 8, 31, 22, 30, tzinfo=timezone.utc)
    today = business_today(now=rollover)
    assert today == date(2026, 9, 1)

    # A task due on the Madrid business day must not be reported as overdue
    # merely because its legacy timestamp is midnight UTC.
    db_session.add_all(
        [
            Task(
                title="Vencida ayer",
                client_id=client.id,
                status=TaskStatus.pending,
                due_date=_naive(2026, 8, 31),
            ),
            Task(
                title="Vence hoy",
                client_id=client.id,
                status=TaskStatus.pending,
                due_date=_naive(2026, 9, 1),
            ),
        ]
    )
    await db_session.flush()
    tasks = (
        (await db_session.execute(select(Task).where(Task.client_id == client.id)))
        .scalars()
        .all()
    )
    task_by_title = {task.title: task for task in tasks}

    # Manual rows keep their civil wall time; timer rows are UTC. The business
    # month includes Sep 1 00:00 Madrid (Aug 31 22:00 UTC) and excludes Oct 1
    # 00:00 Madrid (Sep 30 22:00 UTC).
    overdue_task_id = task_by_title["Vencida ayer"].id
    db_session.add_all(
        [
            TimeEntry(
                minutes=10,
                date=_naive(2026, 8, 31, 23),
                user_id=admin_user.id,
                task_id=overdue_task_id,
            ),
            TimeEntry(
                minutes=20,
                date=_naive(2026, 9, 30, 23),
                user_id=admin_user.id,
                task_id=overdue_task_id,
            ),
            TimeEntry(
                minutes=30,
                date=_naive(2026, 8, 31, 22),
                started_at=_naive(2026, 8, 31, 22),
                user_id=admin_user.id,
                task_id=overdue_task_id,
            ),
            TimeEntry(
                minutes=40,
                date=_naive(2026, 9, 30, 22),
                started_at=_naive(2026, 9, 30, 22),
                user_id=admin_user.id,
                task_id=overdue_task_id,
            ),
        ]
    )
    await db_session.flush()

    prompt: dict[str, str] = {}

    async def create(**kwargs):
        prompt["text"] = kwargs["messages"][0]["content"]
        return SimpleNamespace()

    monkeypatch.setattr(client_advisor, "business_today", lambda: today)
    monkeypatch.setattr(
        client_advisor,
        "get_anthropic_client",
        lambda: SimpleNamespace(
            messages=SimpleNamespace(create=AsyncMock(side_effect=create))
        ),
    )
    monkeypatch.setattr(
        client_advisor, "parse_claude_json", lambda _: {"recommendations": []}
    )

    assert await client_advisor.get_client_advice(db_session, client.id) == []
    assert "Tareas vencidas: 1" in prompt["text"]
    assert "Horas este mes: 0.8h" in prompt["text"]
    assert "Fee mensual:" not in prompt["text"]
    assert "Presupuesto mensual:" not in prompt["text"]

    client.monthly_fee = 0
    client.monthly_budget = 125
    await db_session.flush()
    prompt.clear()

    assert await client_advisor.get_client_advice(db_session, client.id) == []
    assert "Fee mensual: 0 EUR" in prompt["text"]
    assert "Presupuesto mensual: 125 EUR" in prompt["text"]

    client.monthly_fee = None
    await db_session.flush()
    prompt.clear()

    assert await client_advisor.get_client_advice(db_session, client.id) == []
    assert "Fee mensual:" not in prompt["text"]
    assert prompt["text"].index("Presupuesto mensual: 125 EUR") < prompt["text"].index(
        "Tareas:"
    )
