"""The default product configuration keeps the legacy automation engine inert."""

from unittest.mock import MagicMock

import httpx
from sqlalchemy import func, select

from backend.api.routes.automations import execute_automations
from backend.core.modules import HIDDEN_MODULES, hidden_modules
from backend.db.models import AutomationLog, AutomationRule, Delivery, Task
from backend.services.job_catalog import job_definitions


async def test_default_hidden_automation_gate_blocks_jobs_domain_and_http(
    db_session,
    monkeypatch,
):
    # The global test harness enables every module. Remove that override here so
    # this regression exercises the application's real default configuration.
    monkeypatch.delenv("AGENCY_HIDDEN_MODULES", raising=False)
    assert hidden_modules() == HIDDEN_MODULES
    assert "automations" in hidden_modules()

    overdue = next(
        definition
        for definition in job_definitions()
        if definition.spec.key == "overdue_automations"
    )
    assert overdue.enabled is False
    assert overdue.paused_reason == "El módulo de automatizaciones está desactivado."

    db_session.add_all([
        AutomationRule(
            name="Hidden create task",
            trigger="task_completed",
            conditions={},
            action_type="create_task",
            action_config={"title": "Must not be created"},
            is_active=True,
        ),
        AutomationRule(
            name="Hidden Discord send",
            trigger="task_completed",
            conditions={},
            action_type="send_discord",
            action_config={
                "webhook_url": "https://example.invalid/hidden-automation",
                "message": "Must not be sent",
            },
            is_active=True,
        ),
    ])
    await db_session.flush()

    before = {
        "tasks": await db_session.scalar(select(func.count()).select_from(Task)),
        "logs": await db_session.scalar(select(func.count()).select_from(AutomationLog)),
        "deliveries": await db_session.scalar(select(func.count()).select_from(Delivery)),
    }
    http_client = MagicMock(side_effect=AssertionError("hidden automation attempted HTTP"))
    monkeypatch.setattr(httpx, "AsyncClient", http_client)

    await execute_automations("task_completed", {"task_id": 123}, db_session)

    after = {
        "tasks": await db_session.scalar(select(func.count()).select_from(Task)),
        "logs": await db_session.scalar(select(func.count()).select_from(AutomationLog)),
        "deliveries": await db_session.scalar(select(func.count()).select_from(Delivery)),
    }
    assert after == before
    http_client.assert_not_called()
