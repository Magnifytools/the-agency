from datetime import datetime

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes import google_calendar
from backend.db.models import Event, EventType, User, UserRole


def civil(*parts: int) -> datetime:
    """Build the deliberately naive civil/legacy timestamp stored by Event."""
    return datetime(*parts)  # noqa: DTZ001 - database contract is civil naive


NOW_UTC = civil(2026, 10, 25, 0, 30)


def _event(user_id, title, start_time, **values):
    return Event(
        user_id=user_id,
        title=title,
        start_time=start_time,
        event_type=values.pop("event_type", EventType.meeting),
        is_all_day=values.pop("is_all_day", False),
        **values,
    )


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(google_calendar, "utc_now_naive", lambda: NOW_UTC)


@pytest.fixture
def captured_dml(engine):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        operation = statement.lstrip().split(None, 1)[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            statements.append(statement)

    sqlalchemy_event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        sqlalchemy_event.remove(engine.sync_engine, "before_cursor_execute", capture)


async def test_next_meeting_uses_business_civil_time_and_exact_sources(
    admin_client, member_user, db_session, captured_dml,
):
    actor = admin_client.test_user
    actor.google_calendar_connected = True
    actor.google_refresh_token = "retained-credential"
    actor.google_calendar_id = "configured-calendar"
    actor.google_calendar_synced_at = civil(2026, 10, 24, 22, 0)
    expected = _event(actor.id, "Expected", civil(2026, 10, 25, 2, 45), source="google", google_event_id="expected", source_calendar_id="configured-calendar")
    db_session.add_all([
        # At this DST boundary 00:30 UTC is 02:30 civil in Madrid.
        _event(actor.id, "Past civil", civil(2026, 10, 25, 2, 29), source="manual"),
        _event(actor.id, "All day", civil(2026, 10, 25, 2, 31), source="manual", is_all_day=True),
        _event(actor.id, "Wrong type", civil(2026, 10, 25, 2, 31), source="manual", event_type=EventType.other),
        _event(member_user.id, "Other actor", civil(2026, 10, 25, 2, 31), source="manual"),
        _event(actor.id, "Manual with Google id", civil(2026, 10, 25, 2, 31), source="manual", google_event_id="mixed"),
        _event(actor.id, "Legacy Google", civil(2026, 10, 25, 2, 31), source="google", google_event_id="legacy", source_calendar_id=None),
        _event(actor.id, "Other calendar", civil(2026, 10, 25, 2, 31), source="google", google_event_id="other", source_calendar_id="other-calendar"),
        expected,
        _event(actor.id, "Later manual", civil(2026, 10, 25, 3, 0), source="manual"),
    ])
    await db_session.flush()

    before_events = await db_session.scalar(select(func.count(Event.id)))
    captured_dml.clear()
    response = await admin_client.get("/api/calendar/next-meeting")

    assert response.status_code == 200
    assert response.json() == {
        "meeting": {
            "id": expected.id,
            "title": "Expected",
            "date": "2026-10-25",
            "time": "02:45",
            "source": "google",
        },
        "timezone": "Europe/Madrid",
        "connection_status": "connected",
        "last_synced_at": "2026-10-24T22:00:00Z",
    }
    assert await db_session.scalar(select(func.count(Event.id))) == before_events
    assert captured_dml == []


async def test_disconnected_hides_retained_google_but_keeps_manual(
    admin_client, db_session,
):
    actor = admin_client.test_user
    actor.google_calendar_connected = False
    actor.google_refresh_token = None
    actor.google_calendar_id = None
    first_manual = _event(actor.id, "Manual", civil(2026, 10, 25, 2, 40), source="manual")
    second_manual = _event(actor.id, "Manual tie loser", civil(2026, 10, 25, 2, 40), source="manual")
    db_session.add_all([
        _event(actor.id, "Retained Google", civil(2026, 10, 25, 2, 31), source="google", google_event_id="old", source_calendar_id="primary"),
        first_manual,
        second_manual,
    ])
    await db_session.flush()

    response = await admin_client.get("/api/calendar/next-meeting")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "disconnected"
    assert response.json()["meeting"]["title"] == "Manual"
    assert response.json()["meeting"]["id"] == first_manual.id
    assert response.json()["last_synced_at"] is None


async def test_reconnect_required_can_show_matching_retained_google(
    admin_client, db_session,
):
    actor = admin_client.test_user
    actor.google_calendar_connected = False
    actor.google_refresh_token = "retained-credential"
    actor.google_calendar_id = "primary"
    event = _event(
        actor.id,
        "Needs reconnect",
        civil(2026, 10, 25, 2, 35),
        source="google",
        google_event_id="retained",
        source_calendar_id="primary",
    )
    db_session.add(event)
    await db_session.flush()

    response = await admin_client.get("/api/calendar/next-meeting")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "reconnect_required"
    assert response.json()["meeting"] == {
        "id": event.id,
        "title": "Needs reconnect",
        "date": "2026-10-25",
        "time": "02:35",
        "source": "google",
    }


async def test_connected_legacy_configuration_uses_primary_calendar(
    admin_client, db_session,
):
    actor = admin_client.test_user
    actor.google_calendar_connected = True
    actor.google_refresh_token = "retained-credential"
    actor.google_calendar_id = None
    db_session.add(_event(
        actor.id,
        "Primary by default",
        civil(2026, 10, 25, 2, 35),
        source="google",
        google_event_id="orphan",
        source_calendar_id="primary",
    ))
    await db_session.flush()

    response = await admin_client.get("/api/calendar/next-meeting")

    assert response.status_code == 200
    assert response.json()["meeting"] == {
        "id": (await db_session.scalar(select(Event.id).where(Event.title == "Primary by default"))),
        "title": "Primary by default",
        "date": "2026-10-25",
        "time": "02:35",
        "source": "google",
    }
    assert response.json()["connection_status"] == "connected"


async def test_returns_null_for_a_real_empty_calendar(admin_client):
    actor = admin_client.test_user
    actor.google_calendar_connected = False
    actor.google_refresh_token = None
    actor.google_calendar_id = None

    response = await admin_client.get("/api/calendar/next-meeting")

    assert response.status_code == 200
    assert response.json() == {
        "meeting": None,
        "timezone": "Europe/Madrid",
        "connection_status": "disconnected",
        "last_synced_at": None,
    }


async def test_legacy_null_source_is_not_inferred_as_manual(engine):
    """Production accepts historical NULL source rows; they are not attributable."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE events ALTER COLUMN source DROP NOT NULL"))
    user_id = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = User(
                email="next-meeting-null-source@test.local",
                full_name="Null Source",
                hashed_password="unused",
                role=UserRole.member,
                is_active=True,
            )
            db.add(actor)
            await db.flush()
            user_id = actor.id
            await db.execute(text("""
                INSERT INTO events
                    (title,event_type,start_time,is_all_day,user_id,source,created_at,updated_at)
                VALUES
                    ('Legacy NULL','meeting','2026-10-25 02:31',false,:user_id,NULL,now(),now()),
                    ('Explicit manual','meeting','2026-10-25 02:40',false,:user_id,'manual',now(),now())
            """), {"user_id": user_id})
            await db.commit()

            result = await google_calendar.next_meeting(db=db, current_user=actor)
            assert result.meeting is not None
            assert result.meeting.title == "Explicit manual"
            assert result.meeting.source == "manual"
    finally:
        async with engine.begin() as conn:
            if user_id is not None:
                await conn.execute(text("DELETE FROM events WHERE user_id=:id"), {"id": user_id})
                await conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            await conn.execute(text("ALTER TABLE events ALTER COLUMN source SET NOT NULL"))
