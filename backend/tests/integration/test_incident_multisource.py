"""The common inbox preserves identity and decisions across every source kind."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import noload

from backend.db.models import (
    Client, ClientReportPolicy, ClientStatus, Delivery, Notification,
    Project, ProjectStatus, ReportCadence, Task, TaskStatus, WeeklyDigest,
)
from backend.schemas.incident import IncidentDecision
from backend.services.digest_periods import policy_digest_period
from backend.services.incidents import decide_incident, reconcile_recipient

NOW = datetime(2026, 9, 20, 10)


async def setup_sources(db, actor_id):
    client = Client(name="Cliente sintético", status=ClientStatus.active, is_internal=False)
    db.add(client)
    await db.flush()
    project = Project(name="Proyecto sintético", client_id=client.id, owner_id=actor_id,
                      status=ProjectStatus.active, target_end_date=NOW + timedelta(days=3))
    task = Task(title="Tarea sintética", assigned_to=actor_id, status=TaskStatus.pending,
                due_date=NOW - timedelta(days=1))
    policy = ClientReportPolicy(client_id=client.id, enabled=True, cadence=ReportCadence.weekly,
                                responsible_user_id=actor_id)
    start, end = policy_digest_period("weekly", today=NOW.date())
    digest = WeeklyDigest(client_id=client.id, period_start=start - timedelta(days=7),
                          period_end=end - timedelta(days=7), created_by=actor_id)
    db.add_all([project, task, policy, digest])
    await db.flush()
    delivery = Delivery(id=str(uuid4()), dedupe_key=uuid4().hex, actor_id=actor_id,
                        source_kind="digest", source_id=digest.id, source_version="v1",
                        destination_key="isolated", payload={"steps": []}, status="failed",
                        available_at=NOW, expires_at=NOW + timedelta(days=2))
    db.add(delivery)
    await db.flush()
    return project, task, policy, delivery


async def rows(db, actor_id):
    return list((await db.execute(select(Notification).options(noload("*")).where(
        Notification.user_id == actor_id,
    ).order_by(Notification.id))).scalars())


async def test_all_sources_share_snooze_and_resolution_without_parsing_uuid_as_date(db_session, admin_user):
    project, task, policy, delivery = await setup_sources(db_session, admin_user.id)
    result = await reconcile_recipient(db_session, admin_user.id, now=NOW)
    assert result["created"] == 5
    notices = await rows(db_session, admin_user.id)
    assert {n.entity_type for n in notices} == {"task", "project", "client", "delivery"}
    receipt_notice = next(n for n in notices if n.entity_type == "delivery")
    assert receipt_notice.entity_id is None
    assert receipt_notice.entity_key == delivery.id
    assert receipt_notice.link_url == f"/deliveries/{delivery.id}"
    ids = [n.id for n in notices]
    for notice in notices:
        await decide_incident(db_session, admin_user.id, notice.id, IncidentDecision(
            revision=notice.incident_revision, action="snooze",
            until=(NOW + timedelta(days=2)).replace(tzinfo=timezone.utc),
        ), now=NOW)
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(hours=1))
    assert all(n.incident_state == "snoozed" for n in notices)
    assert [n.id for n in await rows(db_session, admin_user.id)] == ids

    task.status = TaskStatus.completed
    project.status = ProjectStatus.completed
    delivery.status = "sent"
    start, end = policy_digest_period("weekly", today=NOW.date())
    db_session.add(WeeklyDigest(client_id=policy.client_id, period_start=start,
                                period_end=end, created_by=admin_user.id))
    await db_session.flush()
    await reconcile_recipient(db_session, admin_user.id, now=NOW + timedelta(hours=2))
    assert all(n.incident_state == "resolved" for n in notices)
    assert all(n.incident_resolution_reason == "condition_cleared" for n in notices)


async def test_source_changes_hide_current_inbox_before_reconciliation_but_preserve_history(
    db_session, admin_user, admin_client, monkeypatch,
):
    for module in ("incidents", "incident_project_conditions", "incident_report_conditions"):
        monkeypatch.setattr(f"backend.services.{module}.business_today", lambda **kw: NOW.date())
    project, task, policy, delivery = await setup_sources(db_session, admin_user.id)
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 5}
    task.status = TaskStatus.completed
    project.status = ProjectStatus.completed
    delivery.status = "sent"
    start, end = policy_digest_period("weekly", today=NOW.date())
    db_session.add(WeeklyDigest(client_id=policy.client_id, period_start=start,
                                period_end=end, created_by=admin_user.id))
    await db_session.commit()
    assert (await admin_client.get("/api/incidents/count")).json() == {"count": 0}
    assert all(n.incident_state == "active" for n in await rows(db_session, admin_user.id))
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    await db_session.commit()
    history = await admin_client.get("/api/incidents", params={"state": "resolved"})
    assert history.status_code == 200, history.text
    assert len(history.json()["items"]) == 5


async def test_legacy_project_adoption_preserves_id_and_ignores_entity_collision(db_session, admin_user):
    project, _, _, _ = await setup_sources(db_session, admin_user.id)
    real = Notification(user_id=admin_user.id, type="project_closing_soon", title="Anterior",
                        entity_type="project", entity_id=project.id, created_at=NOW)
    malformed = Notification(user_id=admin_user.id, type="project_closing_soon", title="Otra entidad",
                             entity_type="task", entity_id=project.id, created_at=NOW)
    db_session.add_all([real, malformed])
    await db_session.flush()
    real_id = real.id
    await reconcile_recipient(db_session, admin_user.id, now=NOW)
    assert real.id == real_id and real.incident_state == "active"
    assert real.link_url == f"/projects/{project.id}"
    assert malformed.incident_state is None
    assert len([n for n in await rows(db_session, admin_user.id)
                if n.type == "project_closing_soon" and n.incident_state]) == 1
