"""One end-to-end oracle for the complete civil Timesheet week.

Individual entry points have focused tests elsewhere.  This regression connects
their persisted shapes to the weekly reader, including the DST boundary, ACLs
and a historical correction that must not move the original civil date.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from backend.db.models import Task, TaskStatus, TimeEntry


pytestmark = pytest.mark.integration


async def test_week_combines_entry_shapes_preserves_history_and_isolates_members(
    admin_client, admin_user, db_session, make_member_client, monkeypatch,
):
    from backend.api.routes import tasks as tasks_route

    member = await make_member_client([("timesheet", True, True)])
    try:
        tasks = [
            Task(title="Semana manual", status=TaskStatus.pending),
            Task(title="Semana panel", status=TaskStatus.pending),
            Task(title="Semana comando", status=TaskStatus.pending),
            Task(title="Semana timer", status=TaskStatus.in_progress),
        ]
        db_session.add_all(tasks)
        await db_session.commit()

        # Manual Timesheet entry on Monday.
        manual = await admin_client.post("/api/time-entries", json={
            "minutes": 15, "task_id": tasks[0].id,
            "date": "2026-10-19T00:00:00", "notes": "Manual",
        })
        assert manual.status_code == 201, manual.text

        # TaskPanel persists an explicit actual total through the task writer.
        monkeypatch.setattr(
            tasks_route, "manual_time_entry_date", lambda: datetime(2026, 10, 20)
        )
        panel = await admin_client.put(
            f"/api/tasks/{tasks[1].id}", json={"actual_minutes": 20}
        )
        assert panel.status_code == 200, panel.text

        # App and extension commands share this durable command endpoint.
        command = await admin_client.post("/api/commands", json={
            "request_key": "timesheet-week-command-20261023",
            "text": 'Registra 25 minutos en la tarea "Semana comando" el 2026-10-23',
            "channel": "app",
        })
        assert command.status_code == 200, command.text
        assert command.json()["status"] == "executed"

        # Timer instants are UTC.  On the DST fallback weekend this instant is
        # Sunday 25 October in Madrid and belongs to the requested civil week.
        timer = TimeEntry(
            user_id=admin_user.id, task_id=tasks[3].id, minutes=30,
            started_at=datetime(2026, 10, 24, 22, 30),
            date=datetime(2026, 10, 24, 22, 30), notes="Timer",
        )
        # Explicit manual dates remain civil.  These two rows bracket the week
        # and must not leak into it.
        outside_before = TimeEntry(
            user_id=admin_user.id, minutes=40, date=datetime(2026, 10, 18),
            notes="Fuera antes",
        )
        outside_after = TimeEntry(
            user_id=admin_user.id, minutes=50, date=datetime(2026, 10, 26),
            notes="Fuera después",
        )
        member_entry = TimeEntry(
            user_id=member.test_user.id, minutes=10,
            date=datetime(2026, 10, 21), notes="Propia miembro",
        )
        db_session.add_all([timer, outside_before, outside_after, member_entry])
        await db_session.commit()

        team = await admin_client.get(
            "/api/time-entries/weekly", params={"week_start": "2026-10-22"}
        )
        assert team.status_code == 200, team.text
        assert team.json()["week_start"] == "2026-10-19"
        assert team.json()["week_end"] == "2026-10-25"
        rows = {row["user_id"]: row for row in team.json()["users"]}
        assert rows[admin_user.id]["total_minutes"] == 90
        assert rows[admin_user.id]["daily_minutes"] == {
            "2026-10-19": 15,
            "2026-10-20": 20,
            "2026-10-21": 0,
            "2026-10-22": 0,
            "2026-10-23": 25,
            "2026-10-24": 0,
            "2026-10-25": 30,
        }
        assert rows[member.test_user.id]["total_minutes"] == 10

        mine = await member.get(
            "/api/time-entries/weekly", params={"week_start": "2026-10-19"}
        )
        assert mine.status_code == 200, mine.text
        assert [(row["user_id"], row["total_minutes"]) for row in mine.json()["users"]] == [
            (member.test_user.id, 10)
        ]

        # A member cannot alter another person's history.
        denied = await member.put(
            f"/api/time-entries/{manual.json()['id']}", json={"minutes": 17}
        )
        assert denied.status_code == 403

        # The owner/admin can correct minutes and notes; the endpoint does not
        # retarget the historical date to today.
        corrected = await admin_client.put(
            f"/api/time-entries/{manual.json()['id']}",
            json={"minutes": 17, "notes": "Manual corregido"},
        )
        assert corrected.status_code == 200, corrected.text
        stored = await db_session.scalar(
            select(TimeEntry).where(TimeEntry.id == manual.json()["id"])
        )
        assert stored is not None
        assert stored.date == datetime(2026, 10, 19)
        assert stored.minutes == 17 and stored.notes == "Manual corregido"

        refreshed = await admin_client.get(
            "/api/time-entries/weekly", params={"week_start": "2026-10-19"}
        )
        refreshed_rows = {row["user_id"]: row for row in refreshed.json()["users"]}
        assert refreshed_rows[admin_user.id]["total_minutes"] == 92
    finally:
        await member.aclose()
