import asyncio

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, CommandReceipt, Project, Task, TaskStatus, TimeEntry, User, UserRole

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
    assert data["intent"] == {"kind": "query_work", "query": "blockers"}
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
    response = await member_client.post("/api/commands", json={"request_key": KEY, "text": "Crea tarea Prohibida"})
    assert response.status_code == 403
    row = await db_session.scalar(select(CommandReceipt).where(CommandReceipt.user_id == member_client.test_user.id))
    assert row.status == "failed" and row.error_code == "forbidden"
    assert await db_session.scalar(select(Task.id).where(Task.title == "Prohibida")) is None


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
    db_session.add_all([Task(title=f"Prioridad {index}", status=TaskStatus.pending) for index in range(27)])
    await db_session.commit()
    receipt = (await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": "Consulta prioridades"})).json()
    query = receipt["result"]["query"]
    assert query["total"] == 27 and len(query["items"]) == 25 and query["has_more"] is True
    second = await admin_client.get(f"/api/commands/{receipt['id']}/query?page=2&page_size=25")
    assert second.status_code == 200
    assert second.json()["page"] == 2 and len(second.json()["items"]) == 2
