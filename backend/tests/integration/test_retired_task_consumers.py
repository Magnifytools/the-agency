"""Retired work leaves operational queues without erasing historical facts."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.db.models import (
    Client,
    Notification,
    Project,
    ProjectStatus,
    Task,
    TaskRecurrenceOccurrence,
    TaskStatus,
    TimeEntry,
)
from backend.services.daily_facts import collect_daily_facts
from backend.services.digest_collector import collect_digest_data
from backend.services.incident_project_conditions import (
    PROJECT_NO_NEXT_ACTION,
    collect_project_conditions,
)
from backend.services.incidents import reconcile_recipient
from backend.services.recurrence import generate_recurring_instances
from backend.services.temporal import business_today, civil_day_utc_bounds

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 20, 10)  # noqa: DTZ001 -- persisted application UTC


def _retire(task: Task) -> None:
    task.retired_at = NOW
    task.retired_reason = "Duplicada durante la revisión"


async def test_operational_search_and_dashboard_exclude_retired_tasks(
    admin_client, admin_user, db_session
):
    active = Task(
        title="Trabajo operativo visible",
        assigned_to=admin_user.id,
        status=TaskStatus.pending,
        scheduled_date=business_today(),
    )
    retired = Task(
        title="Trabajo operativo retirado",
        assigned_to=admin_user.id,
        status=TaskStatus.pending,
        scheduled_date=business_today(),
        due_date=NOW - timedelta(days=1),
    )
    _retire(retired)
    db_session.add_all([active, retired])
    await db_session.flush()

    search = await admin_client.get("/api/search", params={"q": "Trabajo operativo"})
    assert search.status_code == 200, search.text
    assert {row["id"] for row in search.json()["tasks"]} == {active.id}

    today = await admin_client.get("/api/dashboard/today")
    assert today.status_code == 200, today.text
    ids = {
        row["id"]
        for rows in today.json()["by_user"].values()
        for row in rows
    }
    assert active.id in ids
    assert retired.id not in ids


async def test_retired_completed_and_time_remain_daily_evidence_but_open_work_does_not(
    db_session, admin_user
):
    day = date(2026, 9, 20)
    client = Client(name="Cliente con historia retirada")
    db_session.add(client)
    await db_session.flush()
    completed = Task(
        title="Hecho histórico retirado",
        assigned_to=admin_user.id,
        client_id=client.id,
        status=TaskStatus.completed,
        completed_at=NOW,
    )
    pending = Task(
        title="Plan retirado",
        assigned_to=admin_user.id,
        client_id=client.id,
        status=TaskStatus.pending,
        scheduled_date=day + timedelta(days=1),
    )
    _retire(completed)
    _retire(pending)
    db_session.add_all([completed, pending])
    await db_session.flush()
    entry = TimeEntry(
        task_id=pending.id,
        user_id=admin_user.id,
        minutes=47,
        date=NOW,
        started_at=None,
    )
    db_session.add(entry)
    await db_session.flush()

    facts = await collect_daily_facts(db_session, admin_user, day)
    selected = [fact for fact in facts["facts"] if fact.get("task_id") in {completed.id, pending.id}]
    assert {(fact["kind"], fact["task_id"]) for fact in selected} == {
        ("task_completed", completed.id),
        ("time_logged", pending.id),
    }
    assert facts["total_minutes"] >= 47

    digest = await collect_digest_data(db_session, client.id, day, day)
    assert digest["total_minutes"] == 47
    assert {
        row["id"] for row in digest["unassigned"]["completed_tasks"]
    } == {completed.id}
    assert digest["unassigned"]["pending_tasks"] == []


async def test_retiring_source_resolves_open_incident(db_session, admin_user):
    task = Task(
        title="Compromiso retirado",
        assigned_to=admin_user.id,
        status=TaskStatus.pending,
        due_date=NOW - timedelta(days=1),
    )
    db_session.add(task)
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    incident = (await db_session.execute(select(Notification).where(
        Notification.user_id == admin_user.id,
        Notification.entity_type == "task",
        Notification.entity_id == task.id,
    ))).scalar_one()
    assert incident.incident_state == "active"

    _retire(task)
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(minutes=1))
    assert incident.incident_state == "resolved"
    assert incident.incident_resolution_reason == "condition_cleared"


async def test_retired_recurrence_child_does_not_reopen_consumed_occurrence(
    db_session,
):
    target = date(2026, 9, 20)
    template = Task(
        title="Plantilla mensual preservada",
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=target.day,
        status=TaskStatus.pending,
    )
    db_session.add(template)
    await db_session.flush()
    assert await generate_recurring_instances(db_session, target_date=target) == 1
    child = (await db_session.execute(select(Task).where(
        Task.recurring_parent_id == template.id,
    ))).scalar_one()
    _retire(child)
    await db_session.flush()

    assert await generate_recurring_instances(db_session, target_date=target) == 0
    assert await db_session.scalar(select(func.count()).select_from(
        TaskRecurrenceOccurrence
    ).where(
        TaskRecurrenceOccurrence.template_id == template.id,
        TaskRecurrenceOccurrence.date == target,
    )) == 1
    assert await db_session.scalar(select(func.count()).select_from(Task).where(
        Task.recurring_parent_id == template.id,
    )) == 1
    assert template.retired_at is None


async def test_project_views_use_active_work_but_keep_retired_history_and_hours(
    admin_client, admin_user, db_session
):
    client = Client(name="Cliente proyecto retiradas")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto con revisión",
        client_id=client.id,
        owner_id=admin_user.id,
        status=ProjectStatus.active,
        start_date=datetime.combine(business_today(), datetime.min.time()),
    )
    db_session.add(project)
    await db_session.flush()
    active = Task(
        title="Siguiente acción vigente",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        scheduled_date=business_today(),
    )
    retired_open = Task(
        title="Deuda retirada",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        scheduled_date=business_today(),
    )
    completed_at = civil_day_utc_bounds(business_today())[0] + timedelta(hours=1)
    retired_done = Task(
        title="Hecho retirado",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.completed,
        completed_at=completed_at,
    )
    _retire(retired_open)
    _retire(retired_done)
    db_session.add_all([active, retired_open, retired_done])
    await db_session.flush()
    db_session.add(TimeEntry(
        task_id=retired_open.id,
        user_id=admin_user.id,
        minutes=75,
        date=NOW,
    ))
    await db_session.flush()

    detail = await admin_client.get(f"/api/projects/{project.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["hours_used"] == 1.25

    listing = await admin_client.get("/api/projects", params={"page_size": 1000})
    listed = next(row for row in listing.json()["items"] if row["id"] == project.id)
    assert listed["task_count"] == 1
    assert listed["completed_task_count"] == 0

    grouped = await admin_client.get(f"/api/projects/{project.id}/tasks")
    visible_ids = {
        row["id"]
        for row in grouped.json()["unassigned_tasks"]
    } | {
        row["id"]
        for phase in grouped.json()["phases"]
        for row in phase["tasks"]
    }
    assert visible_ids == {active.id}
    assert await db_session.scalar(select(func.count()).select_from(Task).where(
        Task.project_id == project.id,
    )) == 3
    await db_session.refresh(project, attribute_names=["tasks"])
    assert {task.id for task in project.tasks} == {
        active.id,
        retired_open.id,
        retired_done.id,
    }

    conditions = await collect_project_conditions(db_session, admin_user.id, NOW)
    assert not any(
        condition.kind == PROJECT_NO_NEXT_ACTION and condition.entity_id == project.id
        for condition in conditions.values()
    )

    chart = (await admin_client.get(f"/api/projects/{project.id}/burndown")).json()
    assert chart["total_tasks"] == 2
    assert chart["points"][-1]["completed"] == 1
    assert chart["points"][-1]["remaining"] == 1
