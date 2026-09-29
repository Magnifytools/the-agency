"""Activity reads use current source permissions, including after revocation."""
from uuid import uuid4

from sqlalchemy import select

from backend.db.models import (
    Client,
    Notification,
    Project,
    Task,
    UserPermission,
)


async def test_task_activity_is_hidden_without_and_after_read_permission(
    db_session, make_member_client,
):
    denied = await make_member_client([])
    reader = await make_member_client([("tasks", True, False)])
    task = Task(title=f"Private task {uuid4().hex}", assigned_to=denied.test_user.id)
    reader_task = Task(title=f"Readable task {uuid4().hex}", assigned_to=reader.test_user.id)
    db_session.add_all([task, reader_task])
    await db_session.flush()
    hidden = Notification(user_id=denied.test_user.id, type="task_assigned",
                          title=f"Assigned: {task.title}", entity_type="task", entity_id=task.id)
    visible = Notification(user_id=reader.test_user.id, type="task_assigned",
                           title=f"Assigned: {reader_task.title}", entity_type="task", entity_id=reader_task.id)
    independent = Notification(user_id=denied.test_user.id, type="scheduled_meeting",
                               title="Own meeting")
    db_session.add_all([hidden, visible, independent])
    await db_session.commit()

    assert (await denied.get(f"/api/tasks/{task.id}")).status_code == 403
    assert [row["id"] for row in (await denied.get("/api/notifications?limit=1")).json()] == [independent.id]
    assert (await denied.get("/api/notifications/unread-count")).json() == {"count": 1}
    assert (await denied.put(f"/api/notifications/{hidden.id}/read")).status_code == 404
    assert (await denied.put("/api/notifications/read-all")).status_code == 200
    await db_session.refresh(hidden)
    assert hidden.is_read is False
    assert [row["id"] for row in (await reader.get("/api/notifications")).json()] == [visible.id]

    permission = await db_session.scalar(select(UserPermission).where(
        UserPermission.user_id == reader.test_user.id,
        UserPermission.module == "tasks",
    ))
    permission.can_read = False
    await db_session.commit()
    assert (await reader.get(f"/api/tasks/{reader_task.id}")).status_code == 403
    assert (await reader.get("/api/notifications")).json() == []
    assert (await reader.get("/api/notifications/unread-count")).json() == {"count": 0}
    assert (await reader.put(f"/api/notifications/{visible.id}/read")).status_code == 404
    assert (await reader.put("/api/notifications/read-all")).status_code == 200
    await db_session.refresh(visible)
    assert visible.is_read is False


async def test_phase_activity_requires_current_project_read_permission(
    db_session, make_member_client,
):
    member = await make_member_client([("projects", True, False)])
    client = Client(name=f"Private client {uuid4().hex}")
    db_session.add(client)
    await db_session.flush()
    project = Project(name=f"Private project {uuid4().hex}", client_id=client.id)
    db_session.add(project)
    await db_session.flush()
    activity = Notification(user_id=member.test_user.id, type="phase_completed",
                            title=f"Phase in {project.name}", entity_type="project", entity_id=project.id)
    db_session.add(activity)
    await db_session.commit()
    assert [row["id"] for row in (await member.get("/api/notifications")).json()] == [activity.id]

    permission = await db_session.scalar(select(UserPermission).where(
        UserPermission.user_id == member.test_user.id,
        UserPermission.module == "projects",
    ))
    permission.can_read = False
    await db_session.commit()
    assert (await member.get("/api/notifications")).json() == []
    assert (await member.get("/api/notifications/unread-count")).json() == {"count": 0}
    assert (await member.put(f"/api/notifications/{activity.id}/read")).status_code == 404
    assert (await member.put("/api/notifications/read-all")).status_code == 200
    await db_session.refresh(activity)
    assert activity.is_read is False


async def test_rendered_task_summaries_hide_after_revocation_but_own_meeting_remains(
    db_session, make_member_client,
):
    member = await make_member_client([("tasks", True, False)])
    rows = [
        Notification(user_id=member.test_user.id, type="scheduled_morning",
                     title="Morning", message="Private task and own meeting"),
        Notification(user_id=member.test_user.id, type="scheduled_evening",
                     title="Evening", message="Private task recap"),
        Notification(user_id=member.test_user.id, type="scheduled_meeting",
                     title="Own meeting", message="Calendar event"),
        Notification(user_id=member.test_user.id, type="automation",
                     title="Legacy arbitrary content", message="Unscoped legacy content"),
        Notification(user_id=member.test_user.id, type="task_assigned",
                     title="Malformed legacy assignment"),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    assert {row["type"] for row in (await member.get("/api/notifications")).json()} == {
        "scheduled_morning", "scheduled_evening", "scheduled_meeting",
    }

    permission = await db_session.scalar(select(UserPermission).where(
        UserPermission.user_id == member.test_user.id,
        UserPermission.module == "tasks",
    ))
    permission.can_read = False
    await db_session.commit()
    assert [row["type"] for row in (await member.get("/api/notifications")).json()] == ["scheduled_meeting"]
    assert (await member.get("/api/notifications/unread-count")).json() == {"count": 1}
    assert (await member.put("/api/notifications/read-all")).status_code == 200
    await db_session.refresh(rows[0])
    await db_session.refresh(rows[1])
    await db_session.refresh(rows[3])
    assert all(not row.is_read for row in (rows[0], rows[1], rows[3]))
