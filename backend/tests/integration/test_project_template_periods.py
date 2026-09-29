"""Project-template defaults use Madrid's business day when no date is sent."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.api.routes import projects
from backend.db.models import Client, Project, ProjectPhase, ProjectTemplateDB, Task
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration


def _naive(*parts: int) -> datetime:
    """The legacy DateTime columns intentionally store naive values."""
    return datetime(*parts)  # noqa: DTZ001


async def test_template_without_start_date_uses_madrid_business_midnight(
    admin_client, db_session, monkeypatch
):
    rollover = datetime(2026, 9, 21, 22, 30, tzinfo=timezone.utc)
    today = business_today(now=rollover)
    assert today == date(2026, 9, 22)
    monkeypatch.setattr(projects, "business_today", lambda: today)

    client = Client(name=f"Template period {uuid4().hex[:8]}")
    template = ProjectTemplateDB(
        key=f"period_{uuid4().hex}",
        name="Plantilla de período civil",
        phases=[{"name": "Preparación", "default_days": 3}],
        default_tasks=[{"phase": 0, "title": "Tarea de plantilla", "minutes": 30}],
        created_by=admin_client.test_user.id,
    )
    db_session.add_all([client, template])
    await db_session.flush()

    response = await admin_client.post(
        "/api/projects/from-template",
        params={"client_id": client.id, "template_key": template.key},
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    project = await db_session.get(Project, project_id)
    phase = (
        (
            await db_session.execute(
                select(ProjectPhase).where(ProjectPhase.project_id == project_id)
            )
        )
        .scalars()
        .one()
    )
    task = (
        (await db_session.execute(select(Task).where(Task.project_id == project_id)))
        .scalars()
        .one()
    )

    assert project.start_date == _naive(2026, 9, 22)
    assert phase.start_date == _naive(2026, 9, 22)
    assert phase.due_date == _naive(2026, 9, 25)
    assert task.due_date == _naive(2026, 9, 25)


async def test_template_keeps_an_explicit_start_date(
    admin_client, db_session, monkeypatch
):
    monkeypatch.setattr(projects, "business_today", lambda: date(2026, 9, 22))
    client = Client(name=f"Template explicit {uuid4().hex[:8]}")
    template = ProjectTemplateDB(
        key=f"explicit_{uuid4().hex}",
        name="Plantilla con fecha explícita",
        phases=[],
        default_tasks=[],
        created_by=admin_client.test_user.id,
    )
    db_session.add_all([client, template])
    await db_session.flush()

    response = await admin_client.post(
        "/api/projects/from-template",
        params={
            "client_id": client.id,
            "template_key": template.key,
            "start_date": "2026-10-03T14:15:00",
        },
    )
    assert response.status_code == 201, response.text

    project = await db_session.get(Project, response.json()["id"])
    assert project.start_date == _naive(2026, 10, 3, 14, 15)
