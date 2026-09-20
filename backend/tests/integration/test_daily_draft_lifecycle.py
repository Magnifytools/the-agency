"""Saved daily text remains recoverable under retries, races and slow AI."""
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes import dailys
from backend.db.models import DailyUpdate, DailyUpdateStatus, Delivery, Task, TaskStatus, TimeEntry, User, UserRole
from backend.schemas.daily import DailySubmitRequest, DailyEditRequest, DailyEnrichRequest
from backend.services.deliveries import fingerprint, source_version
from backend.services.temporal import utc_now_naive


async def test_save_and_edit_do_not_wait_for_or_call_ai(admin_client, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Saving must not call the enrichment provider")
    monkeypatch.setattr(dailys, "parse_daily_update", forbidden)
    saved = await admin_client.post("/api/dailys", json={"raw_text": "Trabajo revisado"})
    assert saved.status_code == 201
    row = saved.json()
    assert row["revision"] == 1 and row["parsed_data"] is None
    replay = await admin_client.post("/api/dailys", json={"raw_text": "Trabajo revisado"})
    assert replay.json()["id"] == row["id"]
    edited = await admin_client.put(f"/api/dailys/{row['id']}", json={"raw_text": "Nueva nota", "revision": 1})
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2
    retry = await admin_client.put(f"/api/dailys/{row['id']}", json={"raw_text": "Nueva nota", "revision": 1})
    assert retry.status_code == 200 and retry.json()["revision"] == 2
    recovered = await admin_client.get("/api/dailys/for-date", params={"date": row["date"]})
    assert recovered.json()["id"] == row["id"]
    assert recovered.json()["raw_text"] == "Nueva nota"


async def test_stale_edit_and_delete_offer_current_without_overwriting(admin_client):
    saved = (await admin_client.post("/api/dailys", json={"raw_text": "Original"})).json()
    path = f"/api/dailys/{saved['id']}"
    await admin_client.put(path, json={"raw_text": "Otra pestaña", "revision": 1})
    conflict = await admin_client.put(path, json={"raw_text": "Edición local", "revision": 1})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current"]["raw_text"] == "Otra pestaña"
    assert conflict.json()["detail"]["current"]["revision"] == 2
    removed = await admin_client.delete(path, params={"revision": 1})
    assert removed.status_code == 409
    assert (await admin_client.get(path)).json()["raw_text"] == "Otra pestaña"
    blank = await admin_client.put(path, json={"raw_text": "  ", "revision": 2})
    assert blank.status_code == 400


async def test_for_date_is_personal_and_requires_no_creation(admin_client, member_client):
    day = "2026-08-17"
    assert (await member_client.get("/api/dailys/for-date", params={"date": day})).json() is None
    created = await admin_client.post("/api/dailys", json={"raw_text": "Privado", "date": day})
    assert created.status_code == 201
    assert (await member_client.get("/api/dailys/for-date", params={"date": day})).json() is None
    forbidden = await member_client.put(f"/api/dailys/{created.json()['id']}", json={"raw_text": "Cambio", "revision": 1})
    assert forbidden.status_code == 403


async def test_enrichment_failure_leaves_saved_revision_intact(admin_client, monkeypatch):
    saved = (await admin_client.post("/api/dailys", json={"raw_text": "Guardado antes de IA"})).json()
    async def fail(*args, **kwargs):
        raise TimeoutError("provider did not answer")
    monkeypatch.setattr(dailys, "parse_daily_update", fail)
    result = await admin_client.post(f"/api/dailys/{saved['id']}/reparse", json={"revision": 1})
    assert result.status_code == 502
    current = (await admin_client.get(f"/api/dailys/{saved['id']}")).json()
    assert (current["revision"], current["raw_text"], current["parsed_data"]) == (1, saved["raw_text"], None)


async def test_selected_facts_revalidate_additions_and_preserve_saved_history(admin_client, db_session):
    from datetime import datetime
    task = Task(title="Trabajo con evidencia", assigned_to=admin_client.test_user.id, status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    entry = TimeEntry(task_id=task.id, user_id=admin_client.test_user.id, minutes=30, date=datetime(2026, 9, 10))
    db_session.add(entry)
    await db_session.flush()
    preview = (await admin_client.get("/api/dailys/prefill", params={"date": "2026-09-10"})).json()
    selected = next(f for f in preview["facts"] if f["kind"] == "time_logged" and f["task_id"] == task.id)
    entry.minutes = 45
    await db_session.commit()
    stale = await admin_client.post("/api/dailys", json={"date": "2026-09-10", "raw_text": "30 minutos", "source_fact_keys": [selected["key"]]})
    assert stale.status_code == 422
    assert (await admin_client.get("/api/dailys/for-date", params={"date": "2026-09-10"})).json() is None
    fresh = (await admin_client.get("/api/dailys/prefill", params={"date": "2026-09-10"})).json()
    selected = next(f for f in fresh["facts"] if f["kind"] == "time_logged" and f["task_id"] == task.id)
    saved_response = await admin_client.post("/api/dailys", json={"date": "2026-09-10", "raw_text": "45 minutos", "source_fact_keys": [selected["key"]]})
    assert saved_response.status_code == 201, saved_response.text
    saved = saved_response.json()
    assert saved["source_facts"] == [selected]
    entry.minutes = 60
    task.title = "Nombre posterior"
    await db_session.commit()
    edit = await admin_client.put(f"/api/dailys/{saved['id']}", json={"revision": 1, "raw_text": "45 minutos y una nota", "source_fact_keys": [selected["key"]]})
    assert edit.status_code == 200, edit.text
    assert edit.json()["source_facts"] == [selected]
    assert entry.minutes == 60 and task.status == TaskStatus.pending
    current_preview = (await admin_client.get("/api/dailys/prefill", params={"date": "2026-09-10"})).json()
    current = next(f for f in current_preview["facts"] if f["kind"] == "time_logged" and f["task_id"] == task.id)
    duplicate_event = await admin_client.put(
        f"/api/dailys/{saved['id']}",
        json={
            "revision": 2,
            "source_fact_keys": [selected["key"], current["key"]],
        },
    )
    assert duplicate_event.status_code == 422
    assert "dos versiones" in duplicate_event.json()["detail"]
    retained = (await admin_client.get(f"/api/dailys/{saved['id']}")).json()
    assert retained["revision"] == 2 and retained["source_facts"] == [selected]
    replaced = await admin_client.put(
        f"/api/dailys/{saved['id']}",
        json={"revision": 2, "source_fact_keys": [current["key"]]},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["revision"] == 3
    assert replaced.json()["source_facts"] == [current]


async def test_delete_preserves_any_daily_with_receipt_and_deletes_unshared_draft(
    admin_client, db_session
):
    protected = (
        await admin_client.post(
            "/api/dailys", json={"date": "2026-09-11", "raw_text": "Con recibo"}
        )
    ).json()
    now = utc_now_naive()
    db_session.add(
        Delivery(
            id=str(uuid4()),
            dedupe_key=uuid4().hex,
            actor_id=admin_client.test_user.id,
            source_kind="daily",
            source_id=protected["id"],
            source_version="draft-receipt",
            destination_key="test",
            payload={"text": "snapshot", "steps": []},
            status="pending",
            available_at=now,
            expires_at=now,
        )
    )
    await db_session.commit()

    refused = await admin_client.delete(
        f"/api/dailys/{protected['id']}", params={"revision": 1}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "traceability_required"
    assert (await admin_client.get(f"/api/dailys/{protected['id']}")).status_code == 200

    disposable = (
        await admin_client.post(
            "/api/dailys", json={"date": "2026-09-12", "raw_text": "Sin recibo"}
        )
    ).json()
    stale = await admin_client.delete(
        f"/api/dailys/{disposable['id']}", params={"revision": 2}
    )
    assert stale.status_code == 409
    removed = await admin_client.delete(
        f"/api/dailys/{disposable['id']}", params={"revision": 1}
    )
    assert removed.status_code == 204
    assert (await admin_client.get(f"/api/dailys/{disposable['id']}")).status_code == 404


async def _actor(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"daily-race-{uuid4().hex}@test.local", full_name="Daily actor", hashed_password="test", role=UserRole.member, is_active=True)
        db.add(actor)
        await db.commit()
        return actor


async def _cleanup(engine, actor_id):
    async with AsyncSession(engine) as db:
        await db.execute(delete(DailyUpdate).where(DailyUpdate.user_id == actor_id))
        await db.execute(delete(User).where(User.id == actor_id))
        await db.commit()


async def test_concurrent_creations_are_one_saved_daily(engine):
    actor = await _actor(engine)
    request = DailySubmitRequest(raw_text="Una petición repetida", date=date(2026, 9, 20))
    try:
        async def save():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await dailys.submit_daily(request, db, actor)
        first, second = await asyncio.gather(save(), save())
        assert first.id == second.id and first.revision == second.revision == 1
        async with AsyncSession(engine) as db:
            assert await db.scalar(select(func.count()).select_from(DailyUpdate).where(DailyUpdate.user_id == actor.id)) == 1
    finally:
        await _cleanup(engine, actor.id)


@pytest.mark.parametrize("revoke", [False, True])
async def test_slow_enrichment_does_not_lock_or_overwrite_newer_work(engine, monkeypatch, revoke):
    actor = await _actor(engine)
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"projects": [], "general": [{"description": "Texto antiguo"}], "tomorrow": []}
    monkeypatch.setattr(dailys, "parse_daily_update", slow)
    running = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            saved = await dailys.submit_daily(DailySubmitRequest(raw_text="Antes"), db, actor)
        async def enrich():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await dailys.reparse_daily(saved.id, DailyEnrichRequest(revision=1), db, actor)
        running = asyncio.create_task(enrich())
        await asyncio.wait_for(entered.wait(), 3)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            # Finishes while provider is paused: no DB lock spans AI latency.
            updated = await asyncio.wait_for(dailys.edit_daily(saved.id, DailyEditRequest(raw_text="Después", revision=1), db, actor), 3)
            assert updated.revision == 2
            if revoke:
                row = await db.get(User, actor.id)
                row.is_active = False
                await db.commit()
        release.set()
        with pytest.raises(HTTPException) as exc:
            await running
        assert exc.value.status_code == (403 if revoke else 409)
        async with AsyncSession(engine) as db:
            current = await db.get(DailyUpdate, saved.id)
            assert (current.raw_text, current.revision, current.parsed_data) == ("Después", 2, None)
    finally:
        release.set()
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        await _cleanup(engine, actor.id)


async def test_existing_delivery_hash_is_stable_without_source_evidence(admin_client, db_session):
    saved = (await admin_client.post("/api/dailys", json={"raw_text": "Texto histórico"})).json()
    row = await db_session.get(DailyUpdate, saved["id"])
    original = fingerprint([row.user_id, row.date, row.raw_text, row.parsed_data])
    assert source_version("daily", row) == original
    row.source_facts = [{"key": "example"}]
    assert source_version("daily", row) != original


async def test_enrichment_cannot_change_a_shared_daily(engine, monkeypatch):
    actor = await _actor(engine)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"projects": [], "general": [{"description": "New structure"}], "tomorrow": []}
    monkeypatch.setattr(dailys, "parse_daily_update", provider)
    running = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            saved = await dailys.submit_daily(DailySubmitRequest(raw_text="Contenido compartido"), db, actor)
        async def enrich():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await dailys.reparse_daily(saved.id, DailyEnrichRequest(revision=1), db, actor)
        running = asyncio.create_task(enrich())
        await asyncio.wait_for(entered.wait(), 3)
        # Simulate the worker committing a successful delivery of this source.
        # No provider is contacted and no real communication is produced.
        async with AsyncSession(engine) as db:
            row = await db.get(DailyUpdate, saved.id)
            row.status = DailyUpdateStatus.sent
            await db.commit()
        release.set()
        with pytest.raises(HTTPException) as exc:
            await running
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc:
            await enrich()
        assert exc.value.status_code == 409 and calls == 1
        async with AsyncSession(engine) as db:
            row = await db.get(DailyUpdate, saved.id)
            assert row.status == DailyUpdateStatus.sent
            assert row.revision == 1 and row.parsed_data is None
    finally:
        release.set()
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        await _cleanup(engine, actor.id)
