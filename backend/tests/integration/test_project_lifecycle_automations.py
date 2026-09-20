"""Legacy rules cannot bypass the explicit project archive decision."""

import pytest
from sqlalchemy import select

from backend.api.routes.automations import execute_automations
from backend.db.models import AutomationLog, AutomationRule, Client, Project, ProjectStatus


@pytest.mark.parametrize("before,after,success", [
    (ProjectStatus.active, ProjectStatus.completed, False),
    (ProjectStatus.active, ProjectStatus.cancelled, False),
    (ProjectStatus.completed, ProjectStatus.active, False),
    (ProjectStatus.cancelled, ProjectStatus.active, False),
    (ProjectStatus.active, ProjectStatus.on_hold, True),
    (ProjectStatus.on_hold, ProjectStatus.active, True),
])
async def test_legacy_project_status_rule_respects_reviewed_lifecycle(
    db_session, admin_user, before, after, success,
):
    client = Client(name="Lifecycle rule client")
    project = Project(name="Lifecycle rule project", client=client, status=before)
    db_session.add_all([client, project])
    await db_session.flush()
    rule = AutomationRule(
        name="Project status rule", trigger="task_completed", conditions={},
        action_type="change_project_status", is_active=True,
        action_config={"project_id": project.id, "new_status": after.value},
        created_by=admin_user.id,
    )
    db_session.add(rule)
    await db_session.flush()

    await execute_automations("task_completed", {}, db_session)

    await db_session.refresh(project)
    assert project.status == (after if success else before)
    log = (await db_session.execute(select(AutomationLog).where(
        AutomationLog.rule_id == rule.id,
    ))).scalar_one()
    assert log.success is success
    assert log.action_result["outcome"] == ("success" if success else "error")
    if success:
        assert log.action_result["old_status"] == before.value
        assert log.action_result["new_status"] == after.value
    else:
        assert "new_status" not in log.action_result
