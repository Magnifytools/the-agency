import asyncio

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, CommandReceipt, Project, Task, TaskPriority, TaskStatus, TimeEntry, User, UserPermission, UserRole
from backend.services.commands import parse_command

pytestmark = pytest.mark.asyncio

KEY = "command-request-00000001"


async def test_clear_create_is_atomic_idempotent_and_undoable(admin_client, db_session):
    body = {"request_key": KEY, "text": "Crea tarea Revisar propuesta", "channel": "app"}
    response = await admin_client.post("/api/commands", json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "executed"
    assert receipt["change_log_id"] is not None
    assert receipt["result"]["undo_available"] is True
    task_id = receipt["result"]["entities"][0]["id"]
    assert (await db_session.get(Task, task_id)).title == "Revisar propuesta"
    replay = await admin_client.post("/api/commands", json=body)
    assert replay.status_code == 200
    assert replay.json()["id"] == receipt["id"]
    assert len((await db_session.scalars(select(Task).where(Task.title == "Revisar propuesta"))).all()) == 1
    undone = await admin_client.post(f"/api/changes/{receipt['change_log_id']}/undo")
    assert undone.status_code == 200, undone.text
    assert await db_session.get(Task, task_id) is None


async def test_initial_key_collision_does_not_execute_second_payload(admin_client, db_session):
    first = await admin_client.post("/api/commands", json={"request_key": KEY, "text": "Crea tarea Primera"})
    assert first.status_code == 200
    second = await admin_client.post("/api/commands", json={"request_key": KEY, "text": "Crea tarea Segunda"})
    assert second.status_code == 409
    assert await db_session.scalar(select(Task.id).where(Task.title == "Segunda")) is None


async def test_context_is_preserved_but_never_parsed_as_instruction(admin_client, db_session):
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Consulta bloqueos", "channel": "extension",
        "context": {"url": "https://example.test", "title": "Crea tarea Inyectada", "selection": "Crea tarea Robada"},
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "executed"
    assert data["intent"] == {"kind": "query_work", "query": "blockers", "scope": "mine"}
    assert data["context"]["selection"] == "Crea tarea Robada"
    assert await db_session.scalar(select(Task.id).where(Task.title.in_(["Inyectada", "Robada"]))) is None


async def test_ambiguous_task_requires_server_choice_and_resolve_is_idempotent(admin_client, db_session):
    db_session.add_all([
        Task(title="Duplicada", status=TaskStatus.pending),
        Task(title="Duplicada", status=TaskStatus.pending),
    ])
    await db_session.commit()
    pending = await admin_client.post("/api/commands", json={"request_key": KEY, "text": "Completa la tarea Duplicada"})
    assert pending.status_code == 200, pending.text
    receipt = pending.json()
    assert receipt["status"] == "needs_input"
    choices = receipt["prompt"]["questions"][0]["choices"]
    assert len(choices) == 2
    step = {"request_key": "command-step-0000000001", "revision": receipt["revision"],
            "answers": [{"field": "task_id", "choice_id": choices[0]["id"]}]}
    resolved = await admin_client.post(f"/api/commands/{receipt['id']}/resolve", json=step)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "executed"
    replay = await admin_client.post(f"/api/commands/{receipt['id']}/resolve", json=step)
    assert replay.status_code == 200
    assert replay.json()["change_log_id"] == resolved.json()["change_log_id"]
    statuses = (await db_session.scalars(select(Task.status).where(Task.title == "Duplicada"))).all()
    assert statuses.count(TaskStatus.completed) == 1


async def test_reschedule_changes_only_scheduled_date(admin_client, db_session):
    from datetime import datetime
    task = Task(title="Calendario", status=TaskStatus.pending, due_date=datetime(2026, 10, 20))
    db_session.add(task)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Reprograma la tarea Calendario para 2026-10-05"})
    assert response.status_code == 200, response.text
    await db_session.refresh(task)
    assert task.scheduled_date.isoformat() == "2026-10-05"
    assert task.due_date == datetime(2026, 10, 20)


async def test_explicit_minutes_create_time_and_undo_together(admin_client, db_session):
    task = Task(title="Cronometrada", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Registra 35 minutos en la tarea Cronometrada"})
    assert response.status_code == 200, response.text
    receipt = response.json()
    entry = await db_session.scalar(select(TimeEntry).where(TimeEntry.task_id == task.id))
    await db_session.refresh(task)
    assert entry.minutes == 35 and task.actual_minutes == 35
    assert await admin_client.post(f"/api/changes/{receipt['change_log_id']}/undo")
    assert await db_session.scalar(select(TimeEntry.id).where(TimeEntry.task_id == task.id)) is None
    await db_session.refresh(task)
    assert task.actual_minutes is None


async def test_member_without_permission_gets_durable_failed_receipt(member_client, db_session):
    body = {"request_key": KEY, "text": "Crea tarea Prohibida"}
    response = await member_client.post("/api/commands", json=body)
    assert response.status_code == 403
    row = await db_session.scalar(select(CommandReceipt).where(CommandReceipt.user_id == member_client.test_user.id))
    assert row.status == "failed" and row.error_code == "forbidden"
    assert await db_session.scalar(select(Task.id).where(Task.title == "Prohibida")) is None
    # The first request preserves HTTP authorization semantics. An exact replay
    # is the recovery path after a lost response and returns the durable receipt.
    replay = await member_client.post("/api/commands", json=body)
    assert replay.status_code == 200
    assert replay.json()["id"] == str(row.id)
    assert replay.json()["status"] == "failed"


async def test_project_creation_resolves_client_and_does_not_invent_commercial_fields(admin_client, db_session):
    client = Client(name="Acme CMD", status="active")
    db_session.add(client)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Crea proyecto Auditoría para cliente Acme CMD"})
    assert response.status_code == 200, response.text
    project = await db_session.scalar(select(Project).where(Project.name == "Auditoría"))
    assert project.client_id == client.id
    assert project.owner_id is None and project.monthly_fee is None and project.budget_amount is None


async def test_invalid_absolute_date_is_a_recoverable_failed_receipt(admin_client, db_session):
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Reprograma la tarea Calendario para 2026-13-40"})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "invalid_command"
    assert await db_session.scalar(select(CommandReceipt.id).where(CommandReceipt.request_key == KEY))


async def test_bad_resolution_does_not_consume_or_fail_receipt(admin_client, db_session):
    db_session.add_all([Task(title="Ambigua", status=TaskStatus.pending), Task(title="Ambigua", status=TaskStatus.pending)])
    await db_session.commit()
    pending = (await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Completa la tarea Ambigua"})).json()
    response = await admin_client.post(f"/api/commands/{pending['id']}/resolve", json={
        "request_key": "command-step-0000000002", "revision": pending["revision"],
        "answers": [{"field": "task_id", "choice_id": "task:99999999"}],
    })
    assert response.status_code == 409
    current = (await admin_client.get(f"/api/commands/{pending['id']}")).json()
    assert current["status"] == "needs_input" and current["revision"] == pending["revision"]


async def test_receipts_are_owned_and_not_visible_to_other_users(admin_client, make_member_client):
    receipt = (await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Consulta prioridades"})).json()
    other = await make_member_client([("tasks", True, False)])
    try:
        assert (await other.get(f"/api/commands/{receipt['id']}")).status_code == 404
        listing = await other.get("/api/commands")
        assert listing.status_code == 200 and listing.json()["total"] == 0
    finally:
        await other.aclose()


async def test_concurrent_claims_create_one_receipt(engine):
    from backend.core.security import hash_password
    from uuid import uuid4
    email = f"command-race-{uuid4()}@test.local"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(email=email, full_name="Command Race", hashed_password=hash_password("unused"),
                    role=UserRole.admin, is_active=True)
        setup.add(user)
        await setup.commit()
        user_id = user.id

    async def claim(receipt_id: str):
        async with AsyncSession(engine) as writer:
            won = await writer.scalar(insert(CommandReceipt).values(
                id=receipt_id, user_id=user_id, request_key=KEY, request_hash="a" * 64,
                channel="app", raw_text="Consulta prioridades", status="needs_input",
                revision=1, step_replays={},
            ).on_conflict_do_nothing(index_elements=["user_id", "request_key"])
             .returning(CommandReceipt.id))
            await writer.commit()
            return won

    try:
        first, second = await asyncio.gather(claim(str(uuid4())), claim(str(uuid4())))
        assert (first is None) != (second is None)
        async with AsyncSession(engine) as reader:
            count = len((await reader.scalars(select(CommandReceipt.id).where(
                CommandReceipt.user_id == user_id, CommandReceipt.request_key == KEY))).all())
            assert count == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CommandReceipt).where(CommandReceipt.user_id == user_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_query_result_exposes_real_pagination(admin_client, db_session):
    db_session.add_all([Task(title=f"Prioridad {index}", status=TaskStatus.pending,
                             assigned_to=admin_client.test_user.id) for index in range(27)])
    await db_session.commit()
    receipt = (await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Consulta prioridades"})).json()
    query = receipt["result"]["query"]
    assert query["total"] == 27 and len(query["items"]) == 25 and query["has_more"] is True
    second = await admin_client.get(f"/api/commands/{receipt['id']}/query?page=2&page_size=25")
    assert second.status_code == 200
    assert second.json()["page"] == 2 and len(second.json()["items"]) == 2


async def test_query_defaults_to_my_assigned_work_and_orders_business_priority(
    make_member_client, db_session,
):
    mine = await make_member_client([("tasks", True, False)])
    other = await make_member_client([("tasks", True, False)])
    try:
        db_session.add_all([
            Task(title="Mía baja", status=TaskStatus.pending, priority=TaskPriority.low,
                 assigned_to=mine.test_user.id),
            Task(title="Mía urgente", status=TaskStatus.pending, priority=TaskPriority.urgent,
                 assigned_to=mine.test_user.id),
            Task(title="Ajena urgente", status=TaskStatus.pending, priority=TaskPriority.urgent,
                 assigned_to=other.test_user.id),
            Task(title="Sin atribuir", status=TaskStatus.pending, priority=TaskPriority.urgent,
                 assigned_to=None),
        ])
        await db_session.commit()
        response = await mine.post("/api/commands", json={
            "request_key": KEY, "text": "Consulta prioridades",
        })
        assert response.status_code == 200, response.text
        query = response.json()["result"]["query"]
        assert query["scope"] == "mine"
        assert [item["label"] for item in query["items"]] == ["Mía urgente", "Mía baja"]
    finally:
        await mine.aclose()
        await other.aclose()


async def test_team_scope_is_explicit_and_admin_only(
    admin_client, make_member_client, db_session,
):
    member = await make_member_client([("tasks", True, False)])
    try:
        db_session.add(Task(title="Trabajo de equipo", status=TaskStatus.pending,
                            assigned_to=member.test_user.id))
        await db_session.commit()
        denied = await member.post("/api/commands", json={
            "request_key": KEY, "text": "Consulta prioridades del equipo",
        })
        assert denied.status_code == 403
        allowed = await admin_client.post("/api/commands", json={
            "request_key": "command-request-team-0001",
            "text": "Consulta prioridades del equipo",
        })
        assert allowed.status_code == 200, allowed.text
        query = allowed.json()["result"]["query"]
        assert query["scope"] == "team"
        assert "Trabajo de equipo" in [item["label"] for item in query["items"]]
    finally:
        await member.aclose()


async def test_recurring_template_is_not_queried_or_mutated(admin_client, db_session):
    template = Task(title="Cierre recurrente", status=TaskStatus.pending,
                    is_recurring=True, recurrence_pattern="monthly")
    db_session.add(template)
    await db_session.commit()

    query_response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Consulta prioridades del equipo",
    })
    assert query_response.status_code == 200
    assert "Cierre recurrente" not in [
        item["label"] for item in query_response.json()["result"]["query"]["items"]
    ]

    mutation = await admin_client.post("/api/commands", json={
        "request_key": "command-request-template-1",
        "text": "Completa la tarea Cierre recurrente",
    })
    assert mutation.status_code == 200
    assert mutation.json()["status"] == "needs_input"
    await db_session.refresh(template)
    assert template.status == TaskStatus.pending


async def test_quoted_title_preserves_prepositions_and_applies_project_and_relative_date(
    admin_client, db_session, monkeypatch,
):
    from backend.services import commands
    from datetime import date
    client = Client(name="Acme Natural", status="active")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Web nueva", client_id=client.id)
    db_session.add(project)
    await db_session.commit()
    monkeypatch.setattr(commands, "business_today", lambda: date(2026, 9, 17))

    response = await admin_client.post("/api/commands", json={
        "request_key": "command-natural-task-001",
        "text": 'Crea tarea "Hablar con Ana para el lanzamiento" en proyecto "Web nueva" para mañana',
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "executed"
    task = await db_session.scalar(select(Task).where(Task.title == "Hablar con Ana para el lanzamiento"))
    assert task.project_id == project.id and task.client_id == client.id
    assert task.scheduled_date.isoformat() == "2026-09-18"
    assert receipt["result"]["applied"] == {
        "project_id": project.id, "client_id": client.id, "assigned_to": None,
        "scheduled_date": "2026-09-18",
    }
    assert receipt["result"]["applied_labels"] == {
        "project_id": "Web nueva", "client_id": "Acme Natural",
    }


async def test_project_command_resolves_exact_active_short_name_and_reports_applied_values(
    admin_client, db_session,
):
    client = Client(name="Cliente owner", status="active")
    owner = User(email="owner-cmd@test.local", full_name="María Propietaria", short_name="Mery",
                 hashed_password="unused", is_active=True)
    db_session.add_all([client, owner])
    await db_session.commit()
    body = {
        "request_key": "command-natural-project-1",
        "text": 'Crea proyecto "Web con SEO" para cliente "Cliente owner" responsable Mery fecha objetivo 2026-10-02',
    }
    response = await admin_client.post("/api/commands", json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    project = await db_session.scalar(select(Project).where(Project.name == "Web con SEO"))
    assert project.owner_id == owner.id and project.target_end_date.date().isoformat() == "2026-10-02"
    assert receipt["result"]["applied"] == {
        "client_id": client.id, "owner_id": owner.id, "target_date": "2026-10-02",
    }
    assert receipt["result"]["applied_labels"] == {
        "client_id": "Cliente owner", "owner_id": "Mery",
    }
    client.name = "Cliente renombrado"
    owner.short_name = "Nuevo alias"
    await db_session.commit()
    replay = await admin_client.post("/api/commands", json=body)
    assert replay.status_code == 200
    assert replay.json()["result"]["applied_labels"] == receipt["result"]["applied_labels"]


async def test_reschedule_without_date_keeps_deadline_and_receipt_is_explicit(admin_client, db_session):
    from datetime import date, datetime
    task = Task(title="Quitar plan", status=TaskStatus.pending,
                scheduled_date=date(2026, 9, 20), due_date=datetime(2026, 10, 20))
    db_session.add(task)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": "command-natural-unschedule",
        "text": 'Reprograma la tarea "Quitar plan" sin fecha',
    })
    assert response.status_code == 200, response.text
    await db_session.refresh(task)
    assert task.scheduled_date is None and task.due_date == datetime(2026, 10, 20)
    assert response.json()["result"]["applied"]["scheduled_date"] is None


async def test_ambiguous_friday_is_resolved_once_and_receipt_timestamps_are_utc_z(
    admin_client, db_session, monkeypatch,
):
    from backend.services import commands
    from datetime import date
    monkeypatch.setattr(commands, "business_today", lambda: date(2026, 9, 18))  # Friday
    task = Task(title="Viernes ambiguo", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.commit()
    pending = (await admin_client.post("/api/commands", json={
        "request_key": "command-natural-friday-1",
        "text": 'Reprograma la tarea "Viernes ambiguo" para viernes',
    })).json()
    assert pending["status"] == "needs_input"
    assert pending["created_at"].endswith("Z") and pending["updated_at"].endswith("Z")
    choices = pending["prompt"]["questions"][0]["choices"]
    assert [choice["label"] for choice in choices] == ["2026-09-18", "2026-09-25"]
    resolved = await admin_client.post(f"/api/commands/{pending['id']}/resolve", json={
        "request_key": "command-natural-friday-step",
        "revision": pending["revision"],
        "answers": [{"field": "scheduled_date", "choice_id": choices[1]["id"]}],
    })
    assert resolved.status_code == 200, resolved.text
    await db_session.refresh(task)
    assert task.scheduled_date.isoformat() == "2026-09-25"
    assert resolved.json()["intent"]["scheduled_date"] == "2026-09-25"


async def test_explicit_manual_date_and_actor_are_visible_without_actor_inference(
    admin_client, db_session,
):
    task = Task(title="Tiempo fechado", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": "command-natural-time-001",
        "text": 'Registra 45 minutos en la tarea "Tiempo fechado" el 2026-09-10',
    })
    assert response.status_code == 200, response.text
    applied = response.json()["result"]["applied"]
    assert applied["minutes"] == 45 and applied["user_id"] == admin_client.test_user.id
    assert applied["entry_date"] == "2026-09-10"
    assert response.json()["result"]["applied_labels"]["user_id"] == (
        admin_client.test_user.short_name or admin_client.test_user.full_name
    )
    entry = await db_session.scalar(select(TimeEntry).where(TimeEntry.task_id == task.id))
    assert entry.minutes == 45 and entry.date.date().isoformat() == "2026-09-10"
    rejected = await admin_client.post("/api/commands", json={
        "request_key": "command-natural-time-002",
        "text": 'Registra 45 minutos en la tarea "Tiempo fechado" para Ana',
    })
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"


async def test_resolve_permission_loss_is_persisted_as_durable_failure(make_member_client, db_session):
    member = await make_member_client([("tasks", True, True)])
    try:
        db_session.add_all([
            Task(title="Permiso volátil", status=TaskStatus.pending),
            Task(title="Permiso volátil", status=TaskStatus.pending),
        ])
        await db_session.commit()
        pending = (await member.post("/api/commands", json={
            "request_key": "command-natural-permission",
            "text": "Completa la tarea Permiso volátil",
        })).json()
        choice = pending["prompt"]["questions"][0]["choices"][0]
        await db_session.execute(delete(UserPermission).where(UserPermission.user_id == member.test_user.id))
        await db_session.commit()
        # The test dependency holds the authenticated object for this client;
        # mirror the freshly committed permission state on that request actor.
        member.test_user.permissions = []
        response = await member.post(f"/api/commands/{pending['id']}/resolve", json={
            "request_key": "command-natural-perm-step",
            "revision": pending["revision"],
            "answers": [{"field": "task_id", "choice_id": choice["id"]}],
        })
        assert response.status_code == 403
        durable = (await member.get(f"/api/commands/{pending['id']}")).json()
        assert durable["status"] == "failed" and durable["error"]["code"] == "forbidden"
        assert all(status == TaskStatus.pending for status in
                   (await db_session.scalars(select(Task.status).where(Task.title == "Permiso volátil"))).all())
    finally:
        await member.aclose()


async def test_parser_never_absorbs_supported_qualifiers_into_quoted_title(monkeypatch):
    from backend.services import commands
    from datetime import date
    monkeypatch.setattr(commands, "business_today", lambda: date(2026, 9, 17))
    intent = parse_command(
        'Crea tarea "Informe para cliente con SEO" en proyecto "Web" para mañana'
    )
    assert intent == {
        "kind": "create_task", "title": "Informe para cliente con SEO",
        "schedule_mode": "omitted", "project_name": "Web",
        "date_label": "mañana", "scheduled_date": "2026-09-18",
    }


async def test_unquoted_preposition_requires_explicit_literal_confirmation(admin_client, db_session):
    pending = (await admin_client.post("/api/commands", json={
        "request_key": "command-natural-ambiguous",
        "text": "Crea tarea Informe con SEO",
    })).json()
    assert pending["status"] == "needs_input"
    assert await db_session.scalar(select(Task.id).where(Task.title == "Informe con SEO")) is None
    choice = pending["prompt"]["questions"][0]["choices"][0]
    resolved = await admin_client.post(f"/api/commands/{pending['id']}/resolve", json={
        "request_key": "command-natural-ambiguous-step",
        "revision": pending["revision"],
        "answers": [{"field": "literal_title", "choice_id": choice["id"]}],
    })
    assert resolved.status_code == 200, resolved.text
    assert (await db_session.scalar(select(Task.title).where(
        Task.title == "Informe con SEO"))) == "Informe con SEO"


async def test_quoted_project_reference_keeps_date_words_inside_its_name(admin_client, db_session):
    client = Client(name="Cliente quoted ref", status="active")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Web para mañana", client_id=client.id)
    db_session.add(project)
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": "command-quoted-project-ref",
        "text": 'Crea tarea "El informe" en proyecto "Web para mañana"',
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "executed"
    assert receipt["intent"]["project_name"] == "Web para mañana"
    assert "scheduled_date" not in receipt["intent"]
    task = await db_session.scalar(select(Task).where(Task.title == "El informe"))
    assert task.project_id == project.id and task.scheduled_date is None


async def test_log_time_current_friday_requires_date_choice_before_writing(
    admin_client, db_session, monkeypatch,
):
    from backend.services import commands
    from datetime import date
    monkeypatch.setattr(commands, "business_today", lambda: date(2026, 9, 18))
    task = Task(title="Auditoría viernes", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.commit()
    pending = (await admin_client.post("/api/commands", json={
        "request_key": "command-log-friday-choice",
        "text": 'Registra 20 minutos en tarea "Auditoría viernes" el viernes',
    })).json()
    assert pending["status"] == "needs_input"
    assert "entry_date" not in pending["intent"]
    assert await db_session.scalar(select(TimeEntry.id).where(TimeEntry.task_id == task.id)) is None
    choices = pending["prompt"]["questions"][0]["choices"]
    assert [choice["label"] for choice in choices] == ["2026-09-18", "2026-09-25"]


async def test_quoted_task_without_date_executes_with_explicit_null_schedule(admin_client, db_session):
    response = await admin_client.post("/api/commands", json={
        "request_key": "command-quoted-no-date",
        "text": 'Crea tarea "Auditoría" sin fecha',
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "executed"
    assert receipt["intent"]["schedule_mode"] == "none"
    task = await db_session.scalar(select(Task).where(Task.title == "Auditoría"))
    assert task is not None and task.scheduled_date is None


async def test_all_quoted_entity_references_protect_clause_words(monkeypatch):
    from backend.services import commands
    from datetime import date
    monkeypatch.setattr(commands, "business_today", lambda: date(2026, 9, 17))
    cases = [
        ('Crea tarea "Informe" para cliente "Acme para mañana"',
         {"client_name": "Acme para mañana"}),
        ('Crea tarea "Informe" en proyecto "Web para cliente Acme"',
         {"project_name": "Web para cliente Acme"}),
        ('Crea proyecto "Web" para cliente "Acme responsable Nacho"',
         {"client_name": "Acme responsable Nacho"}),
        ('Crea proyecto "Web" para cliente "Acme fecha objetivo mañana"',
         {"client_name": "Acme fecha objetivo mañana"}),
    ]
    for text, expected in cases:
        intent = parse_command(text)
        assert intent["kind"] in {"create_task", "create_project"}, (text, intent)
        assert all(intent.get(key) == value for key, value in expected.items()), (text, intent)
        assert "scheduled_date" not in intent and "target_date" not in intent


async def test_oversized_command_values_fail_durably_before_domain_writers(
    admin_client, db_session,
):
    client = Client(name="Cliente límites", status="active")
    task = Task(title="Tarea límites", status=TaskStatus.pending)
    db_session.add_all([client, task])
    await db_session.commit()
    cases = [
        ("command-limit-task-001", f'Crea tarea "{"T" * 256}"'),
        ("command-limit-project1", f'Crea proyecto "{"P" * 201}" para cliente "Cliente límites"'),
        ("command-limit-minutes1", 'Registra 1441 minutos en tarea "Tarea límites"'),
    ]
    for key, text in cases:
        response = await admin_client.post("/api/commands", json={"request_key": key, "text": text})
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["status"] == "failed"
        assert receipt["error"]["code"] == "invalid_command"
        stored = await db_session.scalar(select(CommandReceipt).where(CommandReceipt.id == receipt["id"]))
        assert stored is not None and stored.status == "failed"
    assert await db_session.scalar(select(Task.id).where(Task.title == "T" * 256)) is None
    assert await db_session.scalar(select(Project.id).where(Project.name == "P" * 201)) is None
    assert await db_session.scalar(select(TimeEntry.id).where(TimeEntry.task_id == task.id)) is None
