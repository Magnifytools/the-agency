"""Cronómetro olvidado: aviso a las 4 h, crítico a las 8 h y corrección al parar."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.db.models import Notification, TimeEntry
from backend.services.incidents import reconcile_recipient

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


async def _running(db_session, user_id: int, hours: float) -> TimeEntry:
    entry = TimeEntry(user_id=user_id, started_at=_now() - timedelta(hours=hours), date=_now(), accumulated_seconds=0)
    db_session.add(entry)
    await db_session.commit()
    return entry


async def _incident(db_session, user_id: int) -> Notification | None:
    return (await db_session.execute(select(Notification).where(
        Notification.user_id == user_id, Notification.type == "timer_running_long",
    ))).scalar_one_or_none()


async def test_a_long_running_timer_warns_then_escalates_and_clears_on_stop(admin_client, db_session):
    user = admin_client.test_user
    entry = await _running(db_session, user.id, 3)
    await reconcile_recipient(db_session, user.id, now=_now())
    assert await _incident(db_session, user.id) is None

    entry.started_at = _now() - timedelta(hours=5)
    await db_session.commit()
    await reconcile_recipient(db_session, user.id, now=_now())
    incident = await _incident(db_session, user.id)
    assert (incident.incident_state, incident.incident_severity) == ("active", "warning")
    assert incident.title.startswith("Cronómetro en marcha desde hace 5 h")
    first_fingerprint = incident.incident_fingerprint

    entry.started_at = _now() - timedelta(hours=9)
    await db_session.commit()
    await reconcile_recipient(db_session, user.id, now=_now())
    await db_session.refresh(incident)
    assert incident.incident_severity == "critical"
    assert incident.incident_fingerprint != first_fingerprint

    stopped = await admin_client.post("/api/timer/stop", json={"timer_id": entry.id, "minutes": 95})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["minutes"] == 95
    await reconcile_recipient(db_session, user.id, now=_now())
    await db_session.refresh(incident)
    assert incident.incident_state == "resolved"


async def test_a_paused_timer_counts_only_what_it_accumulated(admin_client, db_session):
    user = admin_client.test_user
    entry = await _running(db_session, user.id, 10)
    entry.paused_at = _now() - timedelta(hours=9)
    entry.accumulated_seconds = 3600
    await db_session.commit()
    await reconcile_recipient(db_session, user.id, now=_now())
    assert await _incident(db_session, user.id) is None


async def test_stopping_without_a_correction_still_caps_at_eight_hours(admin_client, db_session):
    entry = await _running(db_session, admin_client.test_user.id, 31)
    stopped = await admin_client.post("/api/timer/stop", json={"timer_id": entry.id})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["minutes"] == 480
    too_much = await _running(db_session, admin_client.test_user.id, 1)
    rejected = await admin_client.post("/api/timer/stop", json={"timer_id": too_much.id, "minutes": 721})
    assert rejected.status_code == 422
