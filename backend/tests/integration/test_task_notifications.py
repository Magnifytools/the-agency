"""Avisos de comentarios, @menciones, revisión y "vence mañana" en la campana."""

from datetime import datetime, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import Client, Notification, Project, Task, TaskStatus, UserPermission
from backend.services.task_notifications import notify_due_tomorrow
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration

TASKS_WRITE = [("tasks", True, True)]


async def _notices(db_session, user_id, *types):
    query = (select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)
             .execution_options(populate_existing=True))
    if types:
        query = query.where(Notification.type.in_(types))
    return list((await db_session.execute(query)).scalars())


async def _task(db_session, **fields):
    task = Task(title=fields.pop("title", "Informe mensual"), status=fields.pop("status", TaskStatus.pending), **fields)
    db_session.add(task)
    await db_session.flush()
    return task


async def test_comment_notifies_assignee_and_earlier_commenters_never_the_author(
    admin_client, make_member_client, db_session,
):
    nacho = await make_member_client(TASKS_WRITE)
    otra = await make_member_client(TASKS_WRITE)
    task = await _task(db_session, assigned_to=nacho.test_user.id)

    first = await otra.post(f"/api/tasks/{task.id}/comments", json={"text": "Lo miro yo"})
    assert first.status_code == 201, first.text
    second = await admin_client.post(f"/api/tasks/{task.id}/comments", json={"text": "Ojo con la fecha"})
    assert second.status_code == 201, second.text

    to_nacho = await _notices(db_session, nacho.test_user.id, "task_comment")
    assert [n.title for n in to_nacho] == [
        "Member 1 ha comentado en «Informe mensual»",
        "Admin Integration ha comentado en «Informe mensual»",
    ]
    assert to_nacho[-1].message == "Ojo con la fecha"
    assert to_nacho[-1].link_url == f"/tasks?task={task.id}"
    # Quien ya comentó recibe el siguiente; nadie recibe el suyo.
    assert [n.title for n in await _notices(db_session, otra.test_user.id, "task_comment")] == [
        "Admin Integration ha comentado en «Informe mensual»",
    ]
    assert await _notices(db_session, admin_client.test_user.id, "task_comment") == []
    await nacho.aclose()
    await otra.aclose()


async def test_mention_replaces_the_comment_notice_and_needs_task_access(
    admin_client, make_member_client, db_session,
):
    nacho = await make_member_client(TASKS_WRITE)
    sin_tareas = await make_member_client([("clients", True, False)])
    task = await _task(db_session, assigned_to=nacho.test_user.id)

    response = await admin_client.post(f"/api/tasks/{task.id}/comments", json={
        "text": "@Nacho revisa esto", "mention_ids": [nacho.test_user.id, sin_tareas.test_user.id, 999999],
    })
    assert response.status_code == 201, response.text

    notices = await _notices(db_session, nacho.test_user.id)
    assert [(n.type, n.title) for n in notices] == [
        ("task_mention", "Admin Integration te ha mencionado en «Informe mensual»"),
    ]
    assert await _notices(db_session, sin_tareas.test_user.id) == []
    await nacho.aclose()
    await sin_tareas.aclose()


async def test_review_request_reaches_the_reviewer_and_the_result_the_assignee(
    admin_client, make_member_client, db_session,
):
    nacho = await make_member_client(TASKS_WRITE)
    admin = admin_client.test_user
    project = Project(name="SEO", client=Client(name=f"Revisión {uuid4().hex[:6]}"),
                      owner_id=admin.id, requires_task_review=True)
    db_session.add(project)
    await db_session.flush()
    task = await _task(db_session, assigned_to=nacho.test_user.id, project_id=project.id, client_id=project.client_id)

    sent = await nacho.put(f"/api/tasks/{task.id}", json={"status": "in_review"})
    assert sent.status_code == 200, sent.text
    requested = await _notices(db_session, admin.id, "task_review_requested")
    assert [(n.title, n.message) for n in requested] == [
        ("«Informe mensual» espera revisión", "Member 0 la ha enviado a revisión."),
    ]
    assert await _notices(db_session, nacho.test_user.id, "task_review_requested") == []

    returned = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "in_progress"})
    assert returned.status_code == 200, returned.text
    await nacho.put(f"/api/tasks/{task.id}", json={"status": "in_review"})
    approved = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "completed"})
    assert approved.status_code == 200, approved.text

    result = await _notices(db_session, nacho.test_user.id, "task_review_returned", "task_review_approved")
    assert [(n.type, n.message) for n in result] == [
        ("task_review_returned", "Admin Integration la ha devuelto a En curso."),
        ("task_review_approved", "Admin Integration la ha dado por hecha."),
    ]
    # Dos envíos a revisión, dos avisos; ninguno al responsable por cerrar él mismo.
    assert len(await _notices(db_session, admin.id, "task_review_requested")) == 2
    await nacho.aclose()


async def test_closing_your_own_task_from_review_notifies_nobody(admin_client, db_session):
    task = await _task(db_session, assigned_to=admin_client.test_user.id, status=TaskStatus.in_review)
    response = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    assert await _notices(db_session, admin_client.test_user.id) == []


async def test_due_tomorrow_once_per_task_and_date(make_member_client, db_session):
    nacho = await make_member_client(TASKS_WRITE)
    tomorrow = datetime.combine(business_today() + timedelta(days=1), time.min)
    due = await _task(db_session, title="Vence mañana", assigned_to=nacho.test_user.id, due_date=tomorrow)
    await _task(db_session, title="Ya hecha", assigned_to=nacho.test_user.id, due_date=tomorrow,
                status=TaskStatus.completed)
    await _task(db_session, title="Pasado mañana", assigned_to=nacho.test_user.id,
                due_date=tomorrow + timedelta(days=1))
    await _task(db_session, title="Sin responsable", due_date=tomorrow)

    assert await notify_due_tomorrow(db_session) == 1
    assert await notify_due_tomorrow(db_session) == 0

    notices = await _notices(db_session, nacho.test_user.id)
    assert [(n.type, n.title, n.link_url) for n in notices] == [
        ("task_due_tomorrow", "«Vence mañana» vence mañana", f"/tasks?task={due.id}"),
    ]
    await nacho.aclose()


async def test_task_notices_disappear_from_the_bell_without_task_access(
    admin_client, make_member_client, db_session,
):
    nacho = await make_member_client(TASKS_WRITE)
    task = await _task(db_session, assigned_to=nacho.test_user.id)
    await admin_client.post(f"/api/tasks/{task.id}/comments", json={"text": "Hola"})
    assert [n["type"] for n in (await nacho.get("/api/notifications")).json()] == ["task_comment"]

    permission = (await db_session.execute(select(UserPermission).where(
        UserPermission.user_id == nacho.test_user.id, UserPermission.module == "tasks",
    ))).scalar_one()
    permission.can_read = False
    permission.can_write = False
    await db_session.flush()
    assert (await nacho.get("/api/notifications")).json() == []
    await nacho.aclose()


async def test_assigning_yourself_is_not_news_and_links_open_the_task(admin_client, make_member_client, db_session):
    nacho = await make_member_client(TASKS_WRITE)
    mine = await admin_client.post("/api/tasks", json={"title": "Mía", "assigned_to": admin_client.test_user.id})
    assert mine.status_code == 201, mine.text
    assert await _notices(db_session, admin_client.test_user.id) == []

    theirs = await admin_client.post("/api/tasks", json={"title": "Suya", "assigned_to": nacho.test_user.id})
    notice = (await _notices(db_session, nacho.test_user.id, "task_assigned"))[0]
    assert notice.link_url == f"/tasks?task={theirs.json()['id']}"
    await nacho.aclose()
