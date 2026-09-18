"""Automation actions against real constraints; all outbound HTTP is mocked."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy import select, func
from backend.api.routes import automations
from backend.services.temporal import business_today
from backend.db.models import AutomationRule, AutomationLog, Task, TaskStatus, Client, Project, ProjectPhase


async def rule(db, action, config=None, trigger="task_completed", conditions=None):
    item = AutomationRule(name="Test rule", trigger=trigger, action_type=action,
                          action_config=config or {}, conditions=conditions or {}, is_active=True)
    db.add(item)
    await db.flush()
    return item


async def logs(db):
    return (await db.execute(select(AutomationLog).order_by(AutomationLog.id))).scalars().all()


async def test_hidden_task_hook_changes_task_without_running_rule(db_session, admin_client, monkeypatch):
    task = Task(title="Parent", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    await rule(db_session, "create_task", {"title": "Unexpected child"})
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "automations")
    response = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    assert response.json()["completed_at"] is not None
    assert await db_session.scalar(select(func.count(Task.id))) == 1
    assert await logs(db_session) == []


async def test_missing_condition_skips_rule_without_execution_record(db_session):
    r = await rule(db_session, "create_task", conditions={"project_id": 999})
    await automations.execute_automations("task_completed", {}, db_session)
    assert await logs(db_session) == []
    assert r.run_count == 0


async def test_failed_sql_rule_rolls_back_and_next_rule_succeeds(db_session):
    # Invalid insight target forces a real PostgreSQL FK error, independent
    # of the shared task validator gaining additional client checks.
    bad = await rule(db_session, "create_insight", {"task_id": 987654321})
    good = await rule(db_session, "create_task", {"title": "Good child"})
    await automations.execute_automations("task_completed", {}, db_session)
    records = {item.rule_id: item for item in await logs(db_session)}
    assert records[bad.id].success is False
    assert records[bad.id].action_result["outcome"] == "error"
    assert records[good.id].success is True
    assert await db_session.scalar(select(func.count(Task.id))) == 1
    assert bad.run_count == good.run_count == 1


async def test_create_task_validates_hierarchy_and_derives_client(db_session):
    client = Client(name="Scope A"); other = Client(name="Scope B")
    db_session.add_all([client, other]); await db_session.flush()
    project = Project(name="Scope project", client_id=client.id)
    db_session.add(project); await db_session.flush()
    phase = ProjectPhase(name="Phase", project_id=project.id)
    db_session.add(phase); await db_session.flush()
    bad = await rule(db_session, "create_task", {"phase_id": phase.id, "client_id": other.id})
    good = await rule(db_session, "create_task", {"phase_id": phase.id})
    await automations.execute_automations("task_completed", {}, db_session)
    records = {item.rule_id: item for item in await logs(db_session)}
    assert records[bad.id].success is False
    task = await db_session.get(Task, records[good.id].action_result["task_id"])
    assert (task.project_id, task.phase_id, task.client_id) == (project.id, phase.id, client.id)


async def test_automated_task_lifecycle_preserves_completion_and_advanced_dates(db_session):
    task = Task(title="Lifecycle", status=TaskStatus.pending)
    db_session.add(task); await db_session.flush()
    r = await rule(db_session, "change_task_status", {"task_id": task.id, "new_status": "completed"})
    await automations.execute_automations("task_completed", {}, db_session)
    completed_at = task.completed_at
    assert completed_at is not None and completed_at.tzinfo is None
    await automations.execute_automations("task_completed", {}, db_session)
    assert task.completed_at == completed_at
    r.action_config = {"task_id": task.id, "new_status": "advanced"}
    await automations.execute_automations("task_completed", {}, db_session)
    assert task.completed_at is None and task.advanced_at == business_today()
    r.action_config = {"task_id": task.id, "new_status": "in_progress"}
    await automations.execute_automations("task_completed", {}, db_session)
    assert task.advanced_at is None


async def test_invalid_status_is_error_and_does_not_mutate_task(db_session):
    task = Task(title="Stable", status=TaskStatus.pending)
    db_session.add(task); await db_session.flush()
    await rule(db_session, "change_task_status", {"task_id": task.id, "new_status": "bogus"})
    await automations.execute_automations("task_completed", {}, db_session)
    assert task.status == TaskStatus.pending
    assert (await logs(db_session))[0].success is False


@pytest.mark.parametrize("http_status,success", [(204, True), (429, False), (503, False)])
async def test_discord_response_records_actual_delivery(db_session, monkeypatch, http_status, success):
    import httpx
    response = httpx.Response(http_status)
    http = AsyncMock(); http.post.return_value = response
    context = MagicMock(); context.__aenter__ = AsyncMock(return_value=http); context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: context)
    await rule(db_session, "send_discord", {"webhook_url": "https://example.invalid/webhook", "message": "Test"})
    await automations.execute_automations("task_completed", {}, db_session)
    record = (await logs(db_session))[0]
    assert record.success is success
    assert record.action_result["sent"] is success
    assert record.action_result["outcome"] == ("success" if success else "error")
    http.post.assert_awaited_once()


async def test_missing_delivery_config_is_skipped_not_success(db_session):
    await rule(db_session, "send_discord")
    await automations.execute_automations("task_completed", {}, db_session)
    record = (await logs(db_session))[0]
    assert record.success is False
    assert automations._log_to_dict(record)["outcome"] == "skipped"


async def test_legacy_daily_check_cannot_be_created_or_activated(db_session, admin_client):
    response = await admin_client.post("/api/automations", json={"name": "Unsupported", "trigger": "daily_check", "action_type": "create_task"})
    assert response.status_code == 400
    r = await rule(db_session, "create_task", trigger="daily_check")
    r.is_active = False; await db_session.flush()
    response = await admin_client.post(f"/api/automations/{r.id}/toggle")
    assert response.status_code == 400
    response = await admin_client.put(f"/api/automations/{r.id}", json={"is_active": True})
    assert response.status_code == 400
    await automations.execute_automations("daily_check", {}, db_session)
    assert await logs(db_session) == []
