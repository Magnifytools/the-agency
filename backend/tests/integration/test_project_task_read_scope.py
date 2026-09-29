"""Project metadata remains readable without exposing task or time facts."""

from datetime import date, datetime

import pytest

from backend.db.models import Client, Project, ProjectPhase, Task, TaskStatus, TimeEntry

pytestmark = pytest.mark.integration


async def test_project_task_projections_follow_current_permissions(
    db_session, make_member_client, admin_user,
):
    client = Client(name="Cliente proyecto sin tareas")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Proyecto privado", client_id=client.id, is_recurring=True)
    db_session.add(project)
    await db_session.flush()
    phase = ProjectPhase(project_id=project.id, name="Fase visible", order_index=0)
    task = Task(
        title="Tarea confidencial", client_id=client.id, project_id=project.id,
        status=TaskStatus.completed, completed_at=datetime(2026, 9, 21, 10),  # noqa: DTZ001
        scheduled_date=date(2026, 9, 21),
    )
    db_session.add_all([phase, task])
    await db_session.flush()
    db_session.add(TimeEntry(
        task_id=task.id, user_id=admin_user.id, minutes=90,
        date=datetime(2026, 9, 21, 10),  # noqa: DTZ001
    ))
    await db_session.commit()

    member = await make_member_client([
        ("projects", True, True), ("tasks", False, False),
        ("timesheet", False, False),
    ])
    task_paths = (
        f"/api/projects/{project.id}/tasks",
        f"/api/projects/{project.id}/burndown",
        f"/api/projects/{project.id}/monthly-cycle?month=2026-09",
        f"/api/projects/{project.id}/close-preview?target=completed",
        f"/api/projects/{project.id}/reopen-preview",
    )
    try:
        for path in task_paths:
            response = await member.get(path)
            assert response.status_code == 403, (path, response.text)

        detail = await member.get(f"/api/projects/{project.id}")
        listing = await member.get("/api/projects")
        assert detail.status_code == listing.status_code == 200
        assert detail.json()["name"] == "Proyecto privado"
        assert [item["name"] for item in detail.json()["phases"]] == ["Fase visible"]
        for field in ("progress_percent", "task_count", "completed_task_count"):
            assert detail.json()[field] is None
            assert listing.json()["items"][0][field] is None
        for field in ("hours_used", "hours_used_week", "hours_used_month", "closing_status"):
            assert detail.json()[field] is None
        edited = await member.put(
            f"/api/projects/{project.id}", json={"description": "Cambio autorizado"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["description"] == "Cambio autorizado"
        assert edited.json()["task_count"] is None
        assert edited.json()["progress_percent"] is None

        task_permission = next(
            permission for permission in member.test_user.permissions
            if permission.module == "tasks"
        )
        task_permission.can_read = True
        await db_session.commit()
        # The integration harness reuses one Session across HTTP requests;
        # production opens a fresh Session after this permission change.
        db_session.expunge(project)
        for path in task_paths[:4]:
            response = await member.get(path)
            assert response.status_code == 200, (path, response.text)
        assert (await member.get(task_paths[4])).status_code == 409  # active project
        grouped = (await member.get(task_paths[0])).json()
        grouped_tasks = grouped["unassigned_tasks"] + [
            task for phase in grouped["phases"] for task in phase["tasks"]
        ]
        assert [task["title"] for task in grouped_tasks] == ["Tarea confidencial"]
        assert (await member.get(task_paths[1])).json()["total_tasks"] == 1
        cycle = (await member.get(task_paths[2])).json()
        assert cycle["completed_in_month_count"] == 1
        assert cycle["total_minutes"] is None
        assert cycle["used_hours"] is None
        assert cycle["remaining_hours"] is None
        detail = (await member.get(f"/api/projects/{project.id}")).json()
        listing = (await member.get("/api/projects")).json()["items"][0]
        assert detail["task_count"] == listing["task_count"] == 1
        assert detail["completed_task_count"] == listing["completed_task_count"] == 1
        assert detail["progress_percent"] == listing["progress_percent"] == 100
        assert detail["hours_used"] is None

        time_permission = next(
            permission for permission in member.test_user.permissions
            if permission.module == "timesheet"
        )
        time_permission.can_read = True
        await db_session.commit()
        assert (await member.get(f"/api/projects/{project.id}")).json()["hours_used"] == 1.5
        assert (await member.get(task_paths[2])).json()["used_hours"] == 1.5

        task_permission.can_read = False
        await db_session.commit()
        for path in task_paths:
            assert (await member.get(path)).status_code == 403
        revoked = (await member.get(f"/api/projects/{project.id}")).json()
        assert revoked["task_count"] is None
        assert revoked["hours_used"] is None

        project_permission = next(
            permission for permission in member.test_user.permissions
            if permission.module == "projects"
        )
        project_permission.can_read = False
        await db_session.commit()
        assert (await member.get(f"/api/projects/{project.id}")).status_code == 403
        assert (await member.get("/api/projects")).status_code == 403
    finally:
        await member.aclose()
