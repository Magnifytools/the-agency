from datetime import date, datetime, timedelta

from sqlalchemy import event

from backend.db.models import (
    Client,
    Project,
    Task,
    TaskStatus,
    TimeEntry,
    UserPermission,
)
from backend.services import daily_facts
from backend.services.daily_facts import (
    collect_daily_facts,
    validate_daily_fact_selection,
)


async def test_daily_facts_keep_real_sources_and_exact_minutes(
    db_session, admin_user, engine
):
    day = date(2026, 9, 21)
    client = Client(name="Acme facts")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Web facts", client_id=client.id)
    db_session.add(project)
    await db_session.flush()
    completed = Task(
        title="Terminada",
        status=TaskStatus.completed,
        assigned_to=admin_user.id,
        client_id=client.id,
        project_id=project.id,
        completed_at=datetime(2026, 9, 21, 9),  # noqa: DTZ001
    )
    template = Task(
        title="Plantilla con horas",
        status=TaskStatus.completed,
        assigned_to=admin_user.id,
        client_id=client.id,
        project_id=project.id,
        is_recurring=True,
        completed_at=datetime(2026, 9, 20, 9),  # noqa: DTZ001
    )
    waiting = Task(
        title="Bloqueada",
        status=TaskStatus.waiting,
        assigned_to=admin_user.id,
        waiting_for="Cliente",
        follow_up_date=day + timedelta(days=3),
    )
    tomorrow = Task(
        title="Siguiente",
        status=TaskStatus.pending,
        assigned_to=admin_user.id,
        scheduled_date=day + timedelta(days=1),
    )
    db_session.add_all([completed, template, waiting, tomorrow])
    await db_session.flush()
    entry = TimeEntry(
        task_id=template.id,
        user_id=admin_user.id,
        minutes=37,
        date=datetime(2026, 9, 21),  # noqa: DTZ001
        started_at=None,
    )
    db_session.add(entry)
    await db_session.flush()

    statements = 0

    def count(*_args):
        nonlocal statements
        statements += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        result = await collect_daily_facts(db_session, admin_user, day)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert statements == 3
    assert result["completed_count"] == 1
    assert result["total_minutes"] == 37
    assert {fact["kind"] for fact in result["facts"]} == {
        "task_completed",
        "time_logged",
        "task_waiting",
        "next_step",
    }
    time_fact = next(fact for fact in result["facts"] if fact["kind"] == "time_logged")
    assert time_fact["key"].startswith(f"time_logged:{entry.id}:")
    assert time_fact["minutes"] == 37 and time_fact["task_id"] == template.id
    waiting_fact = next(
        fact for fact in result["facts"] if fact["kind"] == "task_waiting"
    )
    assert (
        "Cliente" in waiting_fact["detail"]
        and (day + timedelta(days=3)).isoformat() in waiting_fact["detail"]
    )

    snapshots = await validate_daily_fact_selection(
        db_session, admin_user, day, [time_fact["key"]]
    )
    assert snapshots[0]["minutes"] == 37

    old_key = time_fact["key"]
    entry.minutes = 38
    await db_session.flush()
    try:
        await validate_daily_fact_selection(db_session, admin_user, day, [old_key])
    except ValueError as exc:
        assert "Unknown or unavailable" in str(exc)
    else:
        raise AssertionError("a changed fact retained its old source key")

    old_waiting_key = waiting_fact["key"]
    waiting.waiting_for = "Legal"
    await db_session.flush()
    try:
        await validate_daily_fact_selection(
            db_session, admin_user, day, [old_waiting_key]
        )
    except ValueError as exc:
        assert "Unknown or unavailable" in str(exc)
    else:
        raise AssertionError("a changed waiting reason retained its old source key")


async def test_daily_fact_selection_rejects_unknown_and_duplicates(
    db_session, admin_user
):
    day = date(2026, 9, 21)
    for keys in (["foreign"], ["same", "same"]):
        try:
            await validate_daily_fact_selection(db_session, admin_user, day, keys)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid source fact selection was accepted")


async def test_daily_facts_respect_module_switches(db_session, admin_user, monkeypatch):
    task = Task(
        title="No debe filtrarse desde módulo oculto",
        status=TaskStatus.completed,
        assigned_to=admin_user.id,
        completed_at=datetime(2026, 9, 21, 9),  # noqa: DTZ001
    )
    db_session.add(task)
    await db_session.flush()
    monkeypatch.setattr(daily_facts, "is_enabled", lambda _module: False)

    result = await collect_daily_facts(db_session, admin_user, date(2026, 9, 21))

    assert result["facts"] == []


async def test_recurring_advanced_task_is_not_a_next_step(db_session, admin_user):
    day = date(2026, 9, 21)
    task = Task(
        title="Plantilla avanzada",
        status=TaskStatus.advanced,
        assigned_to=admin_user.id,
        is_recurring=True,
        advanced_at=day,
        scheduled_date=day + timedelta(days=1),
    )
    db_session.add(task)
    await db_session.flush()

    result = await collect_daily_facts(db_session, admin_user, day)

    assert [fact["kind"] for fact in result["facts"]] == ["task_advanced"]


async def test_daily_facts_do_not_truncate_large_real_time_sets(db_session, admin_user):
    day = date(2026, 9, 21)
    task = Task(
        title="Trabajo repetido",
        status=TaskStatus.pending,
        assigned_to=admin_user.id,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add_all(
        [
            TimeEntry(
                task_id=task.id,
                user_id=admin_user.id,
                minutes=1,
                date=datetime(2026, 9, 21),  # noqa: DTZ001
            )
            for _ in range(1001)
        ]
    )
    await db_session.flush()

    result = await collect_daily_facts(db_session, admin_user, day)

    time_facts = [fact for fact in result["facts"] if fact["kind"] == "time_logged"]
    assert len(time_facts) == 1001
    assert result["total_minutes"] == 1001


async def test_timer_uses_madrid_civil_day_and_timesheet_acl_hides_task_link(
    db_session, member_user
):
    day = date(2026, 9, 21)
    db_session.add(
        UserPermission(
            user_id=member_user.id,
            module="timesheet",
            can_read=True,
            can_write=False,
        )
    )
    task = Task(title="Trabajo nocturno", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    entry = TimeEntry(
        task_id=task.id,
        user_id=member_user.id,
        minutes=12,
        # 22:30 UTC is 00:30 on Sep 21 in Madrid (CEST).
        date=datetime(2026, 9, 20, 22, 30),  # noqa: DTZ001
        started_at=datetime(2026, 9, 20, 22, 30),  # noqa: DTZ001
    )
    db_session.add(entry)
    await db_session.flush()

    today = await collect_daily_facts(db_session, member_user, day)
    previous = await collect_daily_facts(
        db_session, member_user, day - timedelta(days=1)
    )

    assert len(today["facts"]) == 1
    assert today["facts"][0]["key"].startswith(f"time_logged:{entry.id}:")
    assert today["facts"][0]["href"] is None
    assert today["facts"][0]["title"] == "Trabajo nocturno"
    assert today["facts"][0]["detail"].endswith("2026-09-21")
    assert previous["facts"] == []
