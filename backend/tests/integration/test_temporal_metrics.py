"""Business-period boundaries used by active project and dashboard metrics."""
from datetime import date, datetime

import pytest

from backend.db.models import Client, Project, ProjectStatus, Task, TaskStatus, TimeEntry


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def september_business_date(monkeypatch):
    # The dataset exercises a specific month and a deadline due today. Keep
    # those semantics independent of the host's date, timezone and test time.
    from backend.api.routes import client_dashboard, dashboard, projects, time_entries
    from backend.services import client_health
    for module in (client_dashboard, dashboard, projects, time_entries, client_health):
        monkeypatch.setattr(module, "business_today", lambda: date(2026, 9, 17))


async def _project(db, *, recurring=True):
    client = Client(name="Frontera métricas", monthly_budget=1000)
    db.add(client)
    await db.flush()
    project = Project(
        name="Proyecto frontera",
        client_id=client.id,
        status=ProjectStatus.active,
        start_date=datetime(2026, 9, 1),
        is_recurring=recurring,
        monthly_hours_budget=10,
        weekly_hours_budget=5,
    )
    db.add(project)
    await db.flush()
    task = Task(title="Horas frontera", client_id=client.id, project_id=project.id)
    db.add(task)
    await db.flush()
    return client, project, task


async def test_month_metrics_share_manual_civil_and_timer_utc_boundaries(
    admin_client, admin_user, db_session
):
    client, project, task = await _project(db_session)
    task.due_date = datetime(2026, 9, 17)
    rows = [
        # Manual August entry: excluded even though its wall-clock hour falls
        # after Madrid's UTC boundary for September.
        (10, datetime(2026, 8, 31, 23), None),
        (20, datetime(2026, 9, 30, 23), None),
        # 00:00 Madrid on Sep 1: included.
        (30, datetime(2026, 8, 31, 22), datetime(2026, 8, 31, 22)),
        # 00:00 Madrid on Oct 1: excluded.
        (40, datetime(2026, 9, 30, 22), datetime(2026, 9, 30, 22)),
    ]
    db_session.add_all([
        TimeEntry(
            minutes=minutes,
            date=value,
            started_at=started_at,
            user_id=admin_user.id,
            task_id=task.id,
        )
        for minutes, value, started_at in rows
    ])
    await db_session.flush()

    overview = await admin_client.get("/api/dashboard/overview", params={"year": 2026, "month": 9})
    assert overview.status_code == 200, overview.text
    assert overview.json()["hours_this_month"] == pytest.approx(50 / 60, abs=0.1)

    detail = await admin_client.get(f"/api/projects/{project.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["hours_used_month"] == pytest.approx(50 / 60, abs=0.01)

    budget = await admin_client.get(f"/api/timer/project-budget/{project.id}")
    assert budget.status_code == 200, budget.text
    assert budget.json()["month"]["used_hours"] == pytest.approx(50 / 60, abs=0.01)

    health = await admin_client.get(f"/api/clients/{client.id}/health")
    assert health.status_code == 200, health.text
    assert "Coste estimado 33" in health.json()["observations"]["profitability"]

    client_dashboard = await admin_client.get(f"/api/clients/{client.id}/dashboard")
    assert client_dashboard.status_code == 200, client_dashboard.text
    assert client_dashboard.json()["tasks_overdue"] == 0
    assert client_dashboard.json()["hours_this_month"] == pytest.approx(0.8, abs=0.01)
    assert client_dashboard.json()["monthly_hours_breakdown"]["2026-09"] == pytest.approx(0.8, abs=0.01)


async def test_project_burndown_groups_completion_by_madrid_business_date(
    admin_client, db_session
):
    client, project, _ = await _project(db_session, recurring=False)
    db_session.add(Task(
        title="Medianoche local",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.completed,
        completed_at=datetime(2026, 9, 16, 22, 30),
    ))
    await db_session.flush()

    response = await admin_client.get(f"/api/projects/{project.id}/burndown")
    assert response.status_code == 200, response.text
    points = {point["date"]: point for point in response.json()["points"]}
    assert points["2026-09-16"]["completed"] == 0
    assert points["2026-09-17"]["completed"] == 1
