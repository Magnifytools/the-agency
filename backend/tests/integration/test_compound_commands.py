import asyncio
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client, ClientStatus, CommandReceipt, Project, Task, User, UserPermission, UserRole,
)
from backend.services.commands import (
    STATUS_REVIEW, _lock_compound_scope, check_step_replay, execute_or_prompt, parse_command,
    record_step, request_hash, step_hash,
)

pytestmark = pytest.mark.asyncio

KEY = "compound-command-00000001"
STEP = "compound-execute-00000001"


def _text(client="Acme Compound"):
    return (
        'Crea proyecto "Web nueva" para cliente "' + client
        + '" responsable "Nacho Compound" fecha objetivo 2026-10-02 '
          'con primera tarea "Preparar kickoff" asignada a "Nacho Compound" para 2026-09-25'
    )


async def _setup(db_session):
    client = Client(name="Acme Compound", status="active")
    owner = User(
        email="nacho-compound@test.local", full_name="Nacho Compound",
        short_name="Nacho Compound", hashed_password="unused", role=UserRole.member, is_active=True,
    )
    db_session.add_all([client, owner])
    await db_session.commit()
    return client, owner


async def _review(admin_client, text=None):
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": text or _text(), "channel": "app",
    })
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "needs_review"
    return receipt


async def _execute(admin_client, receipt, key=STEP):
    return await admin_client.post(f"/api/commands/{receipt['id']}/execute", json={
        "request_key": key, "revision": receipt["revision"],
    })


async def test_parser_builds_one_bounded_compound_intent():
    intent = parse_command(_text())
    assert intent["kind"] == "create_project_with_task"
    assert intent["project_name"] == "Web nueva"
    assert intent["client_name"] == "Acme Compound"
    assert intent["owner_name"] == "Nacho Compound"
    assert intent["target_date"] == "2026-10-02"
    assert intent["first_task"]["title"] == "Preparar kickoff"
    assert intent["first_task"]["assigned_name"] == "Nacho Compound"
    assert intent["first_task"]["scheduled_date"] == "2026-09-25"


async def test_compound_ambiguity_never_degrades_to_one_simple_create():
    intent = parse_command(
        'Crea proyecto "Web" para cliente "Acme" con primera tarea Preparar para lanzamiento'
    )
    assert intent["kind"] == "invalid"
    assert "primera tarea" in intent["error"]


@pytest.mark.parametrize(("text", "query"), [
    ("¿Qué necesita respuesta mía?", "decisions"),
    ("Qué necesita mi respuesta", "decisions"),
    ("¿Qué decisiones tengo pendientes?", "decisions"),
    ("¿Qué prioridades tengo?", "priorities"),
    ("¿Qué bloqueos tengo?", "blockers"),
])
async def test_parser_accepts_explicit_spanish_question_forms(text, query):
    assert parse_command(text) == {"kind": "query_work", "query": query, "scope": "mine"}


@pytest.mark.parametrize("text", ["decisiones", "bloqueos", "respuesta mía"])
async def test_parser_does_not_infer_query_from_isolated_terms(text):
    assert parse_command(text) == {"kind": "unsupported"}


async def test_query_punctuation_normalization_does_not_change_quoted_write_names():
    intent = parse_command('Crea tarea "¿Decisiones?" sin fecha')
    assert intent["kind"] == "create_task"
    assert intent["title"] == "¿Decisiones?"


async def test_review_is_concrete_and_writes_nothing(admin_client, db_session):
    client, owner = await _setup(db_session)
    receipt = await _review(admin_client)
    assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    assert await db_session.scalar(select(Task.id).where(Task.title == "Preparar kickoff")) is None
    assert receipt["result"]["applied"] == {
        "project_name": "Web nueva", "client_id": client.id, "owner_id": owner.id,
        "target_date": "2026-10-02", "task_title": "Preparar kickoff",
        "assigned_to": owner.id, "scheduled_date": "2026-09-25",
    }
    assert receipt["prompt"]["kind"] == "compound_plan"


async def test_ambiguous_first_task_date_resolves_into_review(admin_client, db_session):
    await _setup(db_session)
    text = (
        'Crea proyecto "Web lunes" para cliente "Acme Compound" '
        'con primera tarea "Preparar lunes" para lunes'
    )
    with patch("backend.services.commands.business_today", return_value=datetime(2026, 9, 21).date()):
        pending = (await admin_client.post("/api/commands", json={
            "request_key": KEY, "text": text,
        })).json()
        assert pending["status"] == "needs_input"
        choice = pending["prompt"]["questions"][0]["choices"][1]
        resolved = await admin_client.post(f"/api/commands/{pending['id']}/resolve", json={
            "request_key": "compound-date-resolution", "revision": pending["revision"],
            "answers": [{"field": "scheduled_date", "choice_id": choice["id"]}],
        })
    assert resolved.status_code == 200, resolved.text
    review = resolved.json()
    assert review["status"] == "needs_review"
    assert review["result"]["applied"]["scheduled_date"] == "2026-09-28"
    executed = await admin_client.post(f"/api/commands/{pending['id']}/execute", json={
        "request_key": "compound-date-execution", "revision": review["revision"],
    })
    assert executed.status_code == 200
    assert executed.json()["status"] == "executed"


async def test_execute_creates_pair_atomically_with_one_grouped_undo(admin_client, db_session):
    client, owner = await _setup(db_session)
    receipt = await _review(admin_client)
    response = await _execute(admin_client, receipt)
    assert response.status_code == 200, response.text
    executed = response.json()
    assert executed["status"] == "executed"
    assert [entity["type"] for entity in executed["result"]["entities"]] == ["project", "task"]
    project = await db_session.scalar(select(Project).where(Project.name == "Web nueva"))
    task = await db_session.scalar(select(Task).where(Task.title == "Preparar kickoff"))
    assert task.project_id == project.id and task.client_id == client.id
    assert project.owner_id == owner.id and task.assigned_to == owner.id
    undone = await admin_client.post(f"/api/changes/{executed['change_log_id']}/undo")
    assert undone.status_code == 200, undone.text
    assert await db_session.get(Task, task.id) is None
    assert await db_session.get(Project, project.id) is None


async def test_ambiguity_never_writes(admin_client, db_session):
    db_session.add_all([
        Client(name="Duplicado Compound", status="active"),
        Client(name="Duplicado Compound", status="active"),
    ])
    await db_session.commit()
    response = await admin_client.post("/api/commands", json={
        "request_key": KEY, "text": _text("Duplicado Compound"),
    })
    assert response.status_code == 200
    pending = response.json()
    assert pending["status"] == "needs_input"
    assert pending["prompt"]["questions"][0]["field"] == "client_id"
    assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    assert await db_session.scalar(select(Task.id).where(Task.title == "Preparar kickoff")) is None


async def test_second_write_failure_rolls_back_project(admin_client, db_session):
    await _setup(db_session)
    receipt = await _review(admin_client)
    with patch("backend.services.commands.create_task", side_effect=HTTPException(422, "task failed")):
        response = await _execute(admin_client, receipt)
    assert response.status_code == 422
    assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    assert await db_session.scalar(select(Task.id).where(Task.title == "Preparar kickoff")) is None


async def test_requires_both_current_write_permissions(make_member_client, db_session):
    await _setup(db_session)
    projects_only = await make_member_client([("projects", True, True), ("tasks", True, False)])
    try:
        response = await projects_only.post("/api/commands", json={
            "request_key": KEY, "text": _text(),
        })
        assert response.status_code == 403
        assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
        assert await db_session.scalar(select(Task.id).where(Task.title == "Preparar kickoff")) is None
    finally:
        await projects_only.aclose()


async def test_execute_rechecks_permissions_after_review(make_member_client, db_session):
    await _setup(db_session)
    member = await make_member_client([("projects", True, True), ("tasks", True, True)])
    try:
        response = await member.post("/api/commands", json={"request_key": KEY, "text": _text()})
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["status"] == "needs_review"
        permission = await db_session.scalar(select(UserPermission).where(
            UserPermission.user_id == member.test_user.id,
            UserPermission.module == "tasks",
        ))
        permission.can_write = False
        await db_session.commit()
        denied = await member.post(f"/api/commands/{receipt['id']}/execute", json={
            "request_key": STEP, "revision": receipt["revision"],
        })
        assert denied.status_code == 403
        assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    finally:
        await member.aclose()


async def test_execute_replay_creates_one_pair(admin_client, db_session):
    await _setup(db_session)
    receipt = await _review(admin_client)
    first = await _execute(admin_client, receipt, "compound-concurrent-step")
    second = await _execute(admin_client, receipt, "compound-concurrent-step")
    assert first.status_code == second.status_code == 200
    assert first.json()["change_log_id"] == second.json()["change_log_id"]
    assert len((await db_session.scalars(select(Project).where(Project.name == "Web nueva"))).all()) == 1
    assert len((await db_session.scalars(select(Task).where(Task.title == "Preparar kickoff"))).all()) == 1


async def test_changed_label_requires_a_fresh_review_without_writing(admin_client, db_session):
    client, _ = await _setup(db_session)
    receipt = await _review(admin_client)
    client.name = "Acme renamed"
    await db_session.commit()
    changed = await _execute(admin_client, receipt)
    assert changed.status_code == 200, changed.text
    updated = changed.json()
    assert updated["status"] == "needs_review"
    assert updated["result"]["message"].startswith("El plan cambió")
    assert updated["result"]["applied_labels"]["client_id"] == "Acme renamed"
    assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    confirmed = await admin_client.post(f"/api/commands/{receipt['id']}/execute", json={
        "request_key": "compound-execute-after-change", "revision": updated["revision"],
    })
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "executed"


async def test_scope_lock_compiles_to_postgres_no_key_update():
    statement = select(Client).with_for_update(key_share=True)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.endswith("FOR NO KEY UPDATE")


async def test_reviewed_scope_locks_block_client_and_user_changes(engine):
    """The reviewed labels and active flags stay stable through both writes."""
    suffix = uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        client = Client(name=f"Locked client {suffix}", status=ClientStatus.active)
        user = User(
            email=f"locked-{suffix}@test.local", full_name=f"Locked user {suffix}",
            short_name=f"Locked {suffix}", hashed_password="unused",
            role=UserRole.member, is_active=True,
        )
        setup.add_all([client, user])
        await setup.commit()
        client_id, user_id = client.id, user.id

    client_update_started = asyncio.Event()
    user_update_started = asyncio.Event()

    async def rename_client():
        async with AsyncSession(engine) as session:
            client_update_started.set()
            await session.execute(update(Client).where(Client.id == client_id).values(
                name=f"Renamed client {suffix}",
            ))
            await session.commit()

    async def deactivate_user():
        async with AsyncSession(engine) as session:
            user_update_started.set()
            await session.execute(update(User).where(User.id == user_id).values(is_active=False))
            await session.commit()

    try:
        async with AsyncSession(engine) as locker:
            locked_client, locked_users = await _lock_compound_scope(
                locker, client_id=client_id, user_ids=[user_id],
            )
            assert locked_client.name == f"Locked client {suffix}"
            assert locked_users[user_id].is_active is True
            rename = asyncio.create_task(rename_client())
            deactivate = asyncio.create_task(deactivate_user())
            await client_update_started.wait()
            await user_update_started.wait()
            await asyncio.sleep(0.1)
            assert not rename.done()
            assert not deactivate.done()
            await locker.commit()
        await asyncio.wait_for(asyncio.gather(rename, deactivate), timeout=2)
        async with AsyncSession(engine) as verify:
            assert await verify.scalar(select(Client.name).where(Client.id == client_id)) == f"Renamed client {suffix}"
            assert await verify.scalar(select(User.is_active).where(User.id == user_id)) is False
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_deactivation_committed_before_confirmation_writes_nothing(admin_client, db_session):
    _, owner = await _setup(db_session)
    receipt = await _review(admin_client)
    owner.is_active = False
    await db_session.commit()
    response = await _execute(admin_client, receipt)
    assert response.status_code == 409
    assert "persona elegida" in response.json()["detail"]
    stored_response = await admin_client.get(f"/api/commands/{receipt['id']}")
    assert stored_response.status_code == 200
    stored = stored_response.json()
    assert stored["status"] == "failed"
    assert stored["error"] == {
        "code": "invalid_command",
        "detail": "Una persona elegida ya no está disponible; vuelve a revisar el plan",
    }
    assert stored["change_log_id"] is None
    assert await db_session.scalar(select(Project.id).where(Project.name == "Web nueva")) is None
    assert await db_session.scalar(select(Task.id).where(Task.title == "Preparar kickoff")) is None


async def test_two_real_sessions_execute_one_reviewed_pair(engine):
    """The receipt row lock and step replay serialize concurrent confirmations."""
    suffix = uuid4().hex[:8]
    client_name = f"Compound race {suffix}"
    owner_name = f"Owner race {suffix}"
    text = (
        f'Crea proyecto "Race project {suffix}" para cliente "{client_name}" '
        f'responsable "{owner_name}" con primera tarea "Race task {suffix}" '
        f'asignada a "{owner_name}" para 2026-09-25'
    )
    receipt_id = str(uuid4())
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        client = Client(name=client_name, status="active")
        actor = User(
            email=f"compound-race-{suffix}@test.local", full_name=owner_name,
            short_name=owner_name, hashed_password="unused", role=UserRole.admin,
            is_active=True,
        )
        setup.add_all([client, actor])
        await setup.flush()
        receipt = CommandReceipt(
            id=receipt_id, user_id=actor.id, request_key=f"compound-race-{suffix}",
            request_hash=request_hash(text, "app", None), channel="app", raw_text=text,
            status="needs_input", intent=parse_command(text), revision=1, step_replays={},
        )
        setup.add(receipt)
        await execute_or_prompt(setup, receipt, actor)
        assert receipt.status == STATUS_REVIEW
        await setup.commit()
        actor_id, client_id = actor.id, client.id

    execute_key = f"compound-step-{suffix}"
    payload_hash = step_hash("execute", 1, {})

    async def confirm():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = (await session.execute(select(CommandReceipt).where(
                CommandReceipt.id == receipt_id,
            ).with_for_update().execution_options(populate_existing=True))).scalar_one()
            if check_step_replay(row, execute_key, payload_hash):
                return row.result
            assert row.status == STATUS_REVIEW and row.revision == 1
            current_actor = await session.get(User, actor_id)
            row.revision += 1
            await execute_or_prompt(session, row, current_actor, reviewed=True)
            record_step(row, execute_key, payload_hash)
            await session.commit()
            return row.result

    try:
        first, second = await asyncio.gather(confirm(), confirm())
        assert first["entities"] == second["entities"]
        async with AsyncSession(engine) as verify:
            assert len((await verify.scalars(select(Project).where(
                Project.name == f"Race project {suffix}",
            ))).all()) == 1
            assert len((await verify.scalars(select(Task).where(
                Task.title == f"Race task {suffix}",
            ))).all()) == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CommandReceipt).where(CommandReceipt.id == receipt_id))
            await cleanup.execute(delete(Task).where(Task.title == f"Race task {suffix}"))
            await cleanup.execute(delete(Project).where(Project.name == f"Race project {suffix}"))
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(User).where(User.id == actor_id))
            await cleanup.commit()


async def test_grouped_undo_refuses_later_project_work(admin_client, db_session):
    await _setup(db_session)
    receipt = await _review(admin_client)
    executed = (await _execute(admin_client, receipt)).json()
    project_id = next(item["id"] for item in executed["result"]["entities"] if item["type"] == "project")
    db_session.add(Task(title="Trabajo posterior", project_id=project_id))
    await db_session.commit()
    undone = await admin_client.post(f"/api/changes/{executed['change_log_id']}/undo")
    assert undone.status_code == 409
    assert await db_session.get(Project, project_id) is not None
