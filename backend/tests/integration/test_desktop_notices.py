"""Avisos del escritorio para la extensión de Chrome (GET /api/notifications/desktop)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db.models import Notification, Task, TaskStatus
from backend.services.incidents import reconcile_recipient
from backend.services.temporal import utc_now_naive

pytestmark = pytest.mark.integration


async def _notice(db_session, user_id, type, task_id, *, is_read=False):
    notice = Notification(user_id=user_id, type=type, title=f"{type} {task_id}", link_url=f"/tasks?task={task_id}",
                          entity_type="task", entity_id=task_id, is_read=is_read)
    db_session.add(notice)
    await db_session.flush()
    return notice.id


async def test_first_call_only_marks_where_to_start(admin_client, db_session):
    me = admin_client.test_user.id
    task = Task(title="Asignada", status=TaskStatus.pending, assigned_to=me)
    db_session.add(task)
    await db_session.flush()
    old = await _notice(db_session, me, "task_mention", task.id)

    first = (await admin_client.get("/api/notifications/desktop")).json()
    assert first["activity"] == [] and first["next_after_id"] == old


async def test_only_unread_actionable_activity_after_the_mark(admin_client, db_session):
    me = admin_client.test_user.id
    task = Task(title="Asignada", status=TaskStatus.pending, assigned_to=me)
    db_session.add(task)
    await db_session.flush()
    start = await _notice(db_session, me, "task_assigned", task.id)
    comment = await _notice(db_session, me, "task_comment", task.id)
    mention = await _notice(db_session, me, "task_mention", task.id)
    await _notice(db_session, me, "task_review_requested", task.id, is_read=True)
    review = await _notice(db_session, me, "task_review_approved", task.id)
    due = await _notice(db_session, me, "task_due_tomorrow", task.id)

    body = (await admin_client.get("/api/notifications/desktop", params={"after_id": start})).json()
    assert [item["id"] for item in body["activity"]] == [mention, review]
    assert body["activity"][0]["link_url"] == f"/tasks?task={task.id}"
    assert body["next_after_id"] == due
    assert comment not in [item["id"] for item in body["activity"]]


async def test_a_burst_comes_in_pages_of_ten(admin_client, db_session):
    me = admin_client.test_user.id
    task = Task(title="Asignada", status=TaskStatus.pending, assigned_to=me)
    db_session.add(task)
    await db_session.flush()
    ids = [await _notice(db_session, me, "task_mention", task.id) for _ in range(12)]

    page = (await admin_client.get("/api/notifications/desktop", params={"after_id": 0})).json()
    assert [item["id"] for item in page["activity"]] == ids[:10]
    assert page["next_after_id"] == ids[9]
    rest = (await admin_client.get("/api/notifications/desktop", params={"after_id": page["next_after_id"]})).json()
    assert [item["id"] for item in rest["activity"]] == ids[10:]


async def test_critical_alerts_are_listed_while_active_and_counted_like_the_bell(admin_client, db_session):
    me = admin_client.test_user.id
    db_session.add(Task(title="Vencida", status=TaskStatus.pending, assigned_to=me,
                        due_date=utc_now_naive() - timedelta(days=3)))
    await db_session.flush()
    await reconcile_recipient(db_session, me, now=utc_now_naive())
    await db_session.commit()
    incident = (await db_session.execute(select(Notification).where(
        Notification.user_id == me, Notification.incident_state == "active",
    ))).scalars().first()
    assert incident is not None

    count = (await admin_client.get("/api/incidents/count")).json()["count"]
    incident.incident_severity = "warning"
    await db_session.commit()
    body = (await admin_client.get("/api/notifications/desktop")).json()
    assert body["alerts"] == count and body["critical"] == []

    incident.incident_severity = "critical"
    await db_session.commit()
    body = (await admin_client.get("/api/notifications/desktop")).json()
    assert [(item["id"], item["fingerprint"]) for item in body["critical"]] == [(incident.id, incident.incident_fingerprint)]

    incident.incident_state = "dismissed"
    await db_session.commit()
    body = (await admin_client.get("/api/notifications/desktop")).json()
    assert body["critical"] == [] and body["alerts"] == count - 1
