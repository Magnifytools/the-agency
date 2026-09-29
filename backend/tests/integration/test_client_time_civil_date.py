"""Client detail reads timer instants and manual civil dates without conflating them."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.api.routes import clients as clients_route
from backend.db.models import BalanceSnapshot, Client, Expense, Income, Task, TimeEntry
from backend.services.temporal import business_today


pytestmark = pytest.mark.integration


async def test_recent_client_time_exposes_timer_discriminator_and_utc_instant(
    admin_client, admin_user, db_session,
):
    client = Client(name="Civil date client")
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Date contract task", client_id=client.id)
    db_session.add(task)
    await db_session.flush()
    timer = TimeEntry(
        task_id=task.id, user_id=admin_user.id, minutes=30,
        date=datetime(2026, 9, 21, 22, 30),
        started_at=datetime(2026, 9, 21, 22, 30),
    )
    manual = TimeEntry(
        task_id=task.id, user_id=admin_user.id, minutes=15,
        date=datetime(2026, 9, 21), started_at=None,
    )
    db_session.add_all([timer, manual])
    await db_session.flush()

    response = await admin_client.get(f"/api/clients/{client.id}/recent-time-entries")

    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert rows[timer.id]["date"] == "2026-09-21T22:30:00"
    assert rows[timer.id]["started_at"] == "2026-09-21T22:30:00Z"
    assert rows[manual.id]["date"] == "2026-09-21T00:00:00"
    assert rows[manual.id]["started_at"] is None


async def test_recent_client_time_limit_ranks_timer_by_business_day(
    admin_client, admin_user, db_session,
):
    client = Client(name="Recent limit client")
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Limited entries", client_id=client.id)
    db_session.add(task)
    await db_session.flush()
    manual = [
        TimeEntry(
            task_id=task.id, user_id=admin_user.id, minutes=5,
            date=datetime(2026, 9, 21), started_at=None,
        )
        for _ in range(10)
    ]
    timer = TimeEntry(
        task_id=task.id, user_id=admin_user.id, minutes=5,
        date=datetime(2026, 9, 21, 22, 30),
        started_at=datetime(2026, 9, 21, 22, 30),
    )
    db_session.add_all([*manual, timer])
    await db_session.flush()

    response = await admin_client.get(
        f"/api/clients/{client.id}/recent-time-entries", params={"limit": 10}
    )

    assert response.status_code == 200, response.text
    ids = [row["id"] for row in response.json()]
    assert len(ids) == 10
    assert ids[0] == timer.id
    assert ids[1:] == sorted((entry.id for entry in manual), reverse=True)[:9]


async def test_client_what_if_uses_one_business_day_for_both_windows(
    admin_client, db_session, monkeypatch,
):
    instant = datetime(2026, 9, 21, 22, 30, tzinfo=timezone.utc)
    calls = []
    def today():
        calls.append(True)
        return business_today(now=instant)
    monkeypatch.setattr(clients_route, "business_today", today)
    client = Client(name="Boundary client")
    db_session.add(client)
    await db_session.flush()
    db_session.add_all([
        Income(date=date(2026, 9, 22) - timedelta(days=180), description="Edge income", amount=600, client_id=client.id),
        Expense(date=date(2026, 9, 22) - timedelta(days=90), description="Edge expense", amount=300),
        BalanceSnapshot(date=date(2026, 9, 22), amount=900),
    ])
    await db_session.flush()

    response = await admin_client.get(f"/api/clients/{client.id}/what-if")

    assert response.status_code == 200, response.text
    assert response.json()["avg_monthly_revenue"] == 100
    assert response.json()["runway_current"] == 9
    assert calls == [True]
