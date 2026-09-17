"""Fail-closed capability and condition contracts for all automation hooks."""
from unittest.mock import AsyncMock
import pytest
from backend.api.routes import automations


@pytest.mark.parametrize("conditions,data,expected", [
    ({"project_id": 99}, {}, False),
    ({"project_id": 99}, {"project_id": None}, False),
    ({"project_id": None}, {}, False),
    ({"project_id": [1, 2]}, {"project_id": 2}, True),
    ({"project_id": 2, "status": "completed"}, {"project_id": 2}, False),
    ({"project_id": 2}, {"project_id": 3}, False),
    ({"flag": False}, {"flag": False}, True),
    ({}, {}, True),
])
def test_conditions_require_present_values(conditions, data, expected):
    assert automations._conditions_match(conditions, data) is expected


@pytest.mark.parametrize("trigger", sorted(automations.VALID_TRIGGERS))
async def test_hidden_module_guards_every_hook_before_database(monkeypatch, trigger):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "automations")
    db = AsyncMock()
    await automations.execute_automations(trigger, {}, db)
    db.execute.assert_not_called()
    db.commit.assert_not_called()


async def test_daily_check_is_not_advertised_or_executable():
    catalog = await automations.list_triggers()
    assert "daily_check" not in {item["key"] for item in catalog["triggers"]}
    assert "daily_check" not in automations.VALID_TRIGGERS
    db = AsyncMock()
    await automations.execute_automations("daily_check", {}, db)
    db.execute.assert_not_called()


async def test_default_capability_keeps_automations_disabled(monkeypatch):
    monkeypatch.delenv("AGENCY_HIDDEN_MODULES", raising=False)
    db = AsyncMock()
    await automations.execute_automations("task_completed", {}, db)
    db.execute.assert_not_called()


@pytest.mark.parametrize("result,outcome", [({"sent": False}, "error"), ({"skipped": True}, "skipped"), ({"sent": True}, "success")])
def test_legacy_action_results_are_interpreted_truthfully(result, outcome):
    assert automations._action_outcome(result, True) == outcome
