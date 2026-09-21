"""Template creation checks every writer permission before creating entities."""

from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from backend.db.models import Client, Project, ProjectTemplateDB
from backend.services.domain_writes import create_project as create_project_write

pytestmark = pytest.mark.integration


async def test_projects_writer_without_tasks_write_can_only_create_empty_template(
    db_session, make_member_client,
):
    client = Client(name=f"Template permission {uuid4().hex[:8]}")
    task_template = ProjectTemplateDB(
        key=f"with_task_{uuid4().hex}",
        name="Plantilla con tarea",
        phases=[],
        default_tasks=[{"title": "Primera acción", "minutes": 30}],
    )
    empty_template = ProjectTemplateDB(
        key=f"empty_{uuid4().hex}",
        name="Plantilla vacía",
        phases=[],
        default_tasks=[],
    )
    db_session.add_all([client, task_template, empty_template])
    await db_session.flush()
    member = await make_member_client([("projects", True, True)])

    with patch("backend.api.routes.projects.create_project_write", wraps=create_project_write) as project_writer:
        denied = await member.post("/api/projects/from-template", params={
            "client_id": client.id,
            "template_key": task_template.key,
        })
        project_writer.assert_not_awaited()
    assert denied.status_code == 403, denied.text
    assert "tasks" in denied.json()["detail"]
    assert await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.client_id == client.id)
    ) == 0

    allowed = await member.post("/api/projects/from-template", params={
        "client_id": client.id,
        "template_key": empty_template.key,
    })
    assert allowed.status_code == 201, allowed.text
    assert await db_session.scalar(
        select(func.count()).select_from(Project).where(Project.client_id == client.id)
    ) == 1
    await member.aclose()
