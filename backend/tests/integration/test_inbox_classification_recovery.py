from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import (
    Client, ClientStatus, InboxNote, InboxNoteStatus, Project, ProjectStatus, Task,
    User, UserPermission, UserRole,
)
from backend.api.routes.inbox import _to_response, convert_to_task, delete_inbox_note, dismiss_note
from backend.schemas.inbox import ConvertToTaskBody
from backend.services import inbox_processing
from backend.services import ai_utils
from backend.config import settings


def _sessions(engine):
    return lambda: AsyncSession(engine, expire_on_commit=False)


def _suggestion(project_id, client_id):
    return {
        "suggested_project": {"id": project_id, "name": "Provider project", "confidence": 0.9},
        "suggested_client": {"id": client_id, "name": "Provider client", "confidence": 0.8},
        "suggested_action": "create_task",
        "suggested_title": "Preparar siguiente acción",
        "suggested_priority": "medium",
        "reasoning": "Coincide con el proyecto.",
    }


async def _setup(engine, suffix):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(
            email=f"inbox-recovery-{suffix}@test.local", full_name="Inbox Recovery",
            hashed_password="unused", role=UserRole.admin, is_active=True,
        )
        client = Client(name=f"Inbox Client {suffix}", status=ClientStatus.active)
        db.add_all([user, client])
        await db.flush()
        project = Project(
            name=f"Inbox Project {suffix}", client_id=client.id, status=ProjectStatus.active,
        )
        note = InboxNote(user_id=user.id, raw_text="Clasificar esto")
        db.add_all([project, note])
        await db.commit()
        return user.id, client.id, project.id, note.id


async def _cleanup(engine, user_id, client_id):
    async with AsyncSession(engine) as db:
        await db.execute(text("DELETE FROM inbox_notes WHERE user_id=:id"), {"id": user_id})
        await db.execute(text("DELETE FROM user_permissions WHERE user_id=:id"), {"id": user_id})
        await db.execute(text("DELETE FROM projects WHERE client_id=:id"), {"id": client_id})
        await db.execute(text("DELETE FROM clients WHERE id=:id"), {"id": client_id})
        await db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
        await db.commit()


async def test_pending_note_survives_request_and_is_classified_by_worker(engine, monkeypatch):
    user_id, client_id, project_id, note_id = await _setup(engine, "success")

    async def classify(*_args):
        return _suggestion(project_id, client_id)

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 0
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.classified
            assert note.ai_suggestion["suggested_project"] == {
                "id": project_id, "name": "Inbox Project success", "confidence": 0.9,
            }
            assert note.ai_suggestion["suggested_client"]["name"] == "Inbox Client success"
            assert note.classification_error_code is None
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_client_permission_revoked_during_provider_requeues_without_old_text(
    engine, monkeypatch,
):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(
            email="inbox-revoke-during@test.local", full_name="Inbox Revoke",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        client = Client(name="Revoked Context Client", status=ClientStatus.active)
        db.add_all([user, client])
        await db.flush()
        project = Project(
            name="Still Visible Project", client_id=client.id, status=ProjectStatus.active,
        )
        note = InboxNote(user_id=user.id, raw_text="Clasificar revocación")
        db.add_all([
            project,
            note,
            UserPermission(user_id=user.id, module="projects", can_read=True, can_write=False),
            UserPermission(user_id=user.id, module="clients", can_read=True, can_write=False),
        ])
        await db.commit()
        user_id, client_id, project_id, note_id = user.id, client.id, project.id, note.id

    entered, release = asyncio.Event(), asyncio.Event()

    async def classify(*_args):
        entered.set()
        await release.wait()
        result = _suggestion(project_id, client_id)
        result["suggested_title"] = "Título con Revoked Context Client"
        return result

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        running = asyncio.create_task(
            inbox_processing.run_inbox_classification_once(_sessions(engine))
        )
        await entered.wait()
        async with AsyncSession(engine) as db:
            permission = (await db.scalars(select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.module == "clients",
            ))).one()
            await db.delete(permission)
            await db.commit()
        release.set()
        assert await running == 0
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.ai_suggestion is None
            remaining = (await db.scalars(select(UserPermission.module).where(
                UserPermission.user_id == user_id,
            ))).all()
            assert remaining == ["projects"]
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_client_permission_revoked_after_success_hides_whole_suggestion(
    engine, monkeypatch,
):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = User(
            email="inbox-revoke-after@test.local", full_name="Inbox Revoke After",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        client = Client(name="Post-success Secret Client", status=ClientStatus.active)
        db.add_all([user, client])
        await db.flush()
        project = Project(name="Visible Project", client_id=client.id, status=ProjectStatus.active)
        note = InboxNote(user_id=user.id, raw_text="Clasificar antes de revocar")
        db.add_all([
            project, note,
            UserPermission(user_id=user.id, module="projects", can_read=True, can_write=False),
            UserPermission(user_id=user.id, module="clients", can_read=True, can_write=False),
        ])
        await db.commit()
        user_id, client_id, project_id, note_id = user.id, client.id, project.id, note.id

    async def classify(*_args):
        result = _suggestion(project_id, client_id)
        result["reasoning"] = "Incluye Post-success Secret Client"
        return result

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 0
        async with AsyncSession(engine) as db:
            permission = (await db.scalars(select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.module == "clients",
            ))).one()
            await db.delete(permission)
            await db.commit()
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            actor = (await db.scalars(
                select(User).where(User.id == user_id).options(selectinload(User.permissions))
            )).one()
            assert note.ai_suggestion["_context_modules"] == ["projects", "clients"]
            assert _to_response(note, actor).ai_suggestion is None
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_late_result_cannot_overwrite_edited_note(engine, monkeypatch):
    user_id, client_id, project_id, note_id = await _setup(engine, "late")
    entered, release = asyncio.Event(), asyncio.Event()

    async def classify(*_args):
        entered.set()
        await release.wait()
        return _suggestion(project_id, client_id)

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        running = asyncio.create_task(
            inbox_processing.run_inbox_classification_once(_sessions(engine))
        )
        await entered.wait()
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id, with_for_update=True)
            note.raw_text = "Texto editado mientras clasificaba"
            note.status = InboxNoteStatus.pending
            await db.commit()
        release.set()
        assert await running == 0
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.raw_text == "Texto editado mientras clasificaba"
            assert note.status == InboxNoteStatus.pending
            assert note.ai_suggestion is None
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_context_change_while_provider_runs_discards_generated_text(engine, monkeypatch):
    user_id, client_id, project_id, note_id = await _setup(engine, "context-change")
    entered, release = asyncio.Event(), asyncio.Event()

    async def classify(*_args):
        entered.set()
        await release.wait()
        result = _suggestion(project_id, client_id)
        result["reasoning"] = "Texto generado con el contexto anterior"
        return result

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        running = asyncio.create_task(
            inbox_processing.run_inbox_classification_once(_sessions(engine))
        )
        await entered.wait()
        async with AsyncSession(engine) as db:
            project = await db.get(Project, project_id)
            project.status = ProjectStatus.on_hold
            await db.commit()
        release.set()
        assert await running == 0
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.ai_suggestion is None
            assert note.classification_error_code is None
            assert note.classification_next_attempt_at is None
    finally:
        await _cleanup(engine, user_id, client_id)


@pytest.mark.parametrize("action", ["delete", "dismiss", "convert"])
async def test_late_provider_result_cannot_overwrite_terminal_action(
    engine, monkeypatch, action,
):
    user_id, client_id, project_id, note_id = await _setup(engine, f"late-{action}")
    entered, release = asyncio.Event(), asyncio.Event()

    async def classify(*_args):
        entered.set()
        await release.wait()
        return _suggestion(project_id, client_id)

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        running = asyncio.create_task(
            inbox_processing.run_inbox_classification_once(_sessions(engine))
        )
        await entered.wait()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = await db.get(User, user_id)
            if action == "delete":
                await delete_inbox_note(note_id, db=db, user=actor)
            elif action == "dismiss":
                await dismiss_note(note_id, db=db, user=actor)
            else:
                await convert_to_task(
                    note_id, ConvertToTaskBody(client_id=client_id), db=db, user=actor,
                )
        release.set()
        assert await running == 0
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            if action == "delete":
                assert note is None
            else:
                expected = InboxNoteStatus.dismissed if action == "dismiss" else InboxNoteStatus.processed
                assert note.status == expected
                assert note.ai_suggestion is None
            for task in (await db.scalars(select(Task).where(Task.created_by == user_id))).all():
                await db.delete(task)
            await db.commit()
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_provider_failure_is_durable_and_backed_off(engine, monkeypatch):
    user_id, client_id, _project_id, note_id = await _setup(engine, "failure")
    calls = 0

    async def classify(*_args):
        nonlocal calls
        calls += 1
        raise RuntimeError("private provider payload")

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 1
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 0
        assert calls == 1
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.classification_error_code == "provider_unavailable"
            now = await db.scalar(text("SELECT timezone('UTC', clock_timestamp())"))
            assert note.classification_next_attempt_at > now
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_incoherent_project_client_suggestion_is_rejected(engine, monkeypatch):
    user_id, client_id, project_id, note_id = await _setup(engine, "mismatch")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        other = Client(name="Other Suggested Client", status=ClientStatus.active)
        db.add(other)
        await db.commit()
        other_id = other.id

    async def classify(*_args):
        return _suggestion(project_id, other_id)

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 1
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.ai_suggestion is None
            assert note.classification_error_code == "invalid_response"
    finally:
        async with AsyncSession(engine) as db:
            other = await db.get(Client, other_id)
            if other:
                await db.delete(other)
                await db.commit()
        await _cleanup(engine, user_id, client_id)


async def test_missing_provider_configuration_is_visible_and_retryable(engine, monkeypatch):
    user_id, client_id, _project_id, note_id = await _setup(engine, "no-provider")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(ai_utils, "_client", None)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 1
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.classification_error_code == "provider_unavailable"
            assert note.classification_next_attempt_at is not None
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_inactive_owner_is_not_sent_to_provider(engine, monkeypatch):
    user_id, client_id, _project_id, note_id = await _setup(engine, "inactive")
    async with AsyncSession(engine) as db:
        user = await db.get(User, user_id)
        user.is_active = False
        await db.commit()

    async def classify(*_args):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", classify)
    try:
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 0
        async with AsyncSession(engine) as db:
            assert (await db.get(InboxNote, note_id)).status == InboxNoteStatus.pending
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_cancelled_cycle_leaves_pending_note_for_restart(engine, monkeypatch):
    user_id, client_id, project_id, note_id = await _setup(engine, "cancel")
    entered = asyncio.Event()

    async def blocked(*_args):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(inbox_processing, "classify_inbox_note", blocked)
    try:
        running = asyncio.create_task(
            inbox_processing.run_inbox_classification_once(_sessions(engine))
        )
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            assert note.status == InboxNoteStatus.pending
            assert note.classification_error_code is None

        async def succeeds(*_args):
            return _suggestion(project_id, client_id)

        monkeypatch.setattr(inbox_processing, "classify_inbox_note", succeeds)
        assert await inbox_processing.run_inbox_classification_once(_sessions(engine)) == 0
        async with AsyncSession(engine) as db:
            assert (await db.get(InboxNote, note_id)).status == InboxNoteStatus.classified
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_public_update_rejects_lifecycle_and_hidden_associations(
    db_session, make_member_client,
):
    client = Client(name="Hidden Inbox Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Hidden Inbox Project", client_id=client.id, status=ProjectStatus.active)
    db_session.add(project)
    await db_session.flush()
    api = await make_member_client([])
    try:
        created = await api.post("/api/inbox", json={"raw_text": "Privada"})
        assert created.status_code == 201
        note_id = created.json()["id"]
        lifecycle = await api.put(
            f"/api/inbox/{note_id}",
            json={"status": "processed", "resolved_as": "task", "resolved_entity_id": 99},
        )
        assert lifecycle.status_code == 422
        association = await api.put(
            f"/api/inbox/{note_id}", json={"project_id": project.id, "client_id": client.id},
        )
        assert association.status_code == 403
    finally:
        await api.aclose()


async def test_manual_classify_only_requeues_durable_note(admin_client, db_session):
    note = InboxNote(
        user_id=admin_client.test_user.id,
        raw_text="Reintentar",
        status=InboxNoteStatus.classified,
        ai_suggestion={"suggested_title": "Vieja"},
        classification_error_code="provider_unavailable",
        classification_next_attempt_at=await db_session.scalar(
            text("SELECT timezone('UTC', clock_timestamp()) + interval '5 minutes'")
        ),
    )
    db_session.add(note)
    await db_session.flush()
    await db_session.refresh(note)
    previous_updated_at = note.updated_at

    response = await admin_client.post(f"/api/inbox/{note.id}/classify")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["ai_suggestion"] is None
    assert body["classification_error_code"] is None
    assert body["classification_next_attempt_at"] is None
    await db_session.refresh(note)
    assert note.updated_at > previous_updated_at


async def test_manual_assignment_closes_pending_and_clearing_it_requeues(
    admin_client, db_session,
):
    client = Client(name="Manual Inbox Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    note = InboxNote(
        user_id=admin_client.test_user.id,
        raw_text="Asignación manual",
        status=InboxNoteStatus.pending,
        classification_error_code="provider_unavailable",
        classification_next_attempt_at=await db_session.scalar(
            text("SELECT timezone('UTC', clock_timestamp()) + interval '5 minutes'")
        ),
    )
    db_session.add(note)
    await db_session.flush()

    assigned = await admin_client.put(
        f"/api/inbox/{note.id}", json={"client_id": client.id},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "classified"
    assert assigned.json()["classification_error_code"] is None

    cleared = await admin_client.put(
        f"/api/inbox/{note.id}", json={"client_id": None, "project_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "pending"


async def test_terminal_note_transitions_cannot_create_a_second_outcome(
    admin_client, db_session,
):
    client = Client(name="Terminal Inbox Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    processed = InboxNote(
        user_id=admin_client.test_user.id, raw_text="Procesada",
        status=InboxNoteStatus.processed, resolved_as="task", resolved_entity_id=999999,
    )
    dismissed = InboxNote(
        user_id=admin_client.test_user.id, raw_text="Descartada",
        status=InboxNoteStatus.dismissed, resolved_as="dismissed",
    )
    db_session.add_all([processed, dismissed])
    await db_session.flush()

    dismiss_processed = await admin_client.post(f"/api/inbox/{processed.id}/dismiss")
    assert dismiss_processed.status_code == 409
    convert_dismissed = await admin_client.post(
        f"/api/inbox/{dismissed.id}/convert-to-task", json={"client_id": client.id},
    )
    assert convert_dismissed.status_code == 409


async def test_convert_and_dismiss_race_has_one_terminal_outcome(engine):
    user_id, client_id, _project_id, note_id = await _setup(engine, "terminal-race")

    async def convert():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = await db.get(User, user_id)
            try:
                result = await convert_to_task(
                    note_id, ConvertToTaskBody(client_id=client_id), db=db, user=actor,
                )
                return 200, result
            except HTTPException as exc:
                return exc.status_code, None

    async def dismiss():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = await db.get(User, user_id)
            try:
                result = await dismiss_note(note_id, db=db, user=actor)
                return 200, result
            except HTTPException as exc:
                return exc.status_code, None

    try:
        results = await asyncio.gather(convert(), dismiss())
        assert sorted(status for status, _ in results) == [200, 409]
        async with AsyncSession(engine) as db:
            note = await db.get(InboxNote, note_id)
            tasks = (await db.scalars(
                select(Task).where(Task.created_by == user_id)
            )).all()
            assert (note.status, len(tasks)) in {
                (InboxNoteStatus.processed, 1),
                (InboxNoteStatus.dismissed, 0),
            }
            for task in tasks:
                await db.delete(task)
            await db.commit()
    finally:
        await _cleanup(engine, user_id, client_id)


async def test_revoked_suggestion_is_not_used_for_conversion(db_session, make_member_client):
    api = await make_member_client([("tasks", True, True)])
    client = Client(name="Formerly Visible Client", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    note = InboxNote(
        user_id=api.test_user.id,
        raw_text="No usar contexto revocado",
        status=InboxNoteStatus.classified,
        ai_suggestion={
            **_suggestion(None, client.id),
            "_context_modules": ["clients"],
        },
    )
    db_session.add(note)
    await db_session.flush()
    try:
        response = await api.post(f"/api/inbox/{note.id}/convert-to-task", json={})
        assert response.status_code == 400
        assert "cliente" in response.text.lower()
    finally:
        await api.aclose()


async def test_source_is_restricted_to_real_capture_points(admin_client):
    response = await admin_client.post(
        "/api/inbox", json={"raw_text": "Origen falso", "source": "trusted_admin"},
    )
    assert response.status_code == 422
