"""Explicit null lifecycle states are rejected before touching PostgreSQL."""
import pytest
from pydantic import ValidationError

from backend.db.models import Client, Project, ProjectStatus, Task, TaskStatus
from backend.schemas.project import ProjectUpdate
from backend.schemas.task import TaskUpdate


def test_update_schemas_distinguish_omitted_status_from_explicit_null():
    assert "status" not in ProjectUpdate(name="Proyecto").model_fields_set
    assert "status" not in TaskUpdate(title="Tarea").model_fields_set
    with pytest.raises(ValidationError):
        ProjectUpdate(status=None)
    with pytest.raises(ValidationError):
        TaskUpdate(status=None)


@pytest.mark.asyncio
async def test_http_null_status_is_422_and_omission_preserves_database(
    admin_client, db_session,
):
    client = Client(name="Null status contract")
    project = Project(
        name="Before project", client=client, status=ProjectStatus.active,
    )
    task = Task(
        title="Before task", project=project, status=TaskStatus.pending,
    )
    db_session.add_all([client, project, task])
    await db_session.commit()
    project_id, task_id = project.id, task.id

    project_null = await admin_client.put(
        f"/api/projects/{project_id}", json={"status": None},
    )
    task_null = await admin_client.put(
        f"/api/tasks/{task_id}", json={"status": None},
    )
    assert project_null.status_code == 422, project_null.text
    assert task_null.status_code == 422, task_null.text

    project_update = await admin_client.put(
        f"/api/projects/{project_id}", json={"name": "After project"},
    )
    task_update = await admin_client.put(
        f"/api/tasks/{task_id}", json={"title": "After task"},
    )
    assert project_update.status_code == 200, project_update.text
    assert task_update.status_code == 200, task_update.text

    db_session.expire_all()
    persisted_project = await db_session.get(Project, project_id)
    persisted_task = await db_session.get(Task, task_id)
    assert persisted_project.status == ProjectStatus.active
    assert persisted_project.name == "After project"
    assert persisted_task.status == TaskStatus.pending
    assert persisted_task.title == "After task"
