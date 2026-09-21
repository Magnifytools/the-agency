from __future__ import annotations
import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestTone,
    Task,
    TaskStatus,
    User,
    WeeklyDigest,
)
from backend.services.digest_generation import generate_locked_digest, regenerate_digest
from backend.services.digest_generator import _validate_sources

pytestmark = pytest.mark.integration
PERIOD = (date(2026, 9, 7), date(2026, 9, 13))


def facts(name="Cliente"):
    return {
        "client_name": name,
        "source_catalog": {
            "task:1": {
                "kind": "task",
                "class": "task_completed",
                "id": 1,
                "label": "Hecho",
            },
            "aggregate:hours": {
                "kind": "aggregate",
                "class": "aggregate",
                "label": "Horas",
            },
        },
    }


def generated():
    return {
        "greeting": "Hola",
        "date": "",
        "sections": {
            "done": [
                {"title": "Hecho", "description": "Detalle", "source_keys": ["task:1"]}
            ],
            "need": [],
            "next": [],
            "metrics": [
                {
                    "title": "Horas",
                    "description": "Dos",
                    "source_keys": ["aggregate:hours"],
                }
            ],
        },
        "closing": "Fin",
    }


async def test_same_key_replays_and_new_key_creates_a_legitimate_version(
    admin_client, db_session
):
    client = Client(name="Replay", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value=facts(),
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            return_value=generated(),
        ) as provider,
    ):
        payload = {
            "client_id": client.id,
            "period_start": str(PERIOD[0]),
            "period_end": str(PERIOD[1]),
            "generation_key": "same-generation-key",
        }
        first = await admin_client.post("/api/digests/generate", json=payload)
        replay = await admin_client.post("/api/digests/generate", json=payload)
        second = await admin_client.post(
            "/api/digests/generate",
            json={**payload, "generation_key": "new-generation-key"},
        )
    assert first.status_code == replay.status_code == second.status_code == 200
    assert first.json()["id"] == replay.json()["id"] != second.json()["id"]
    assert provider.await_count == 2
    assert "_generation" not in first.json()["raw_context"]


async def test_key_conflict_and_recovery_before_and_after_confirmation(
    admin_client, db_session
):
    client = Client(name="Recover", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    key = "recover-generation-key"
    missing = await admin_client.get(f"/api/digests/generation/{key}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "generation_not_confirmed"
    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value=facts(),
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            return_value=generated(),
        ),
    ):
        created = await admin_client.post(
            "/api/digests/generate",
            json={
                "client_id": client.id,
                "period_start": str(PERIOD[0]),
                "period_end": str(PERIOD[1]),
                "generation_key": key,
            },
        )
        conflict = await admin_client.post(
            "/api/digests/generate",
            json={
                "client_id": client.id,
                "period_start": "2026-08-31",
                "period_end": "2026-09-06",
                "generation_key": key,
            },
        )
    recovered = await admin_client.get(f"/api/digests/generation/{key}")
    assert recovered.status_code == 200
    assert recovered.json()["id"] == created.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "generation_key_conflict"


async def test_provider_runs_without_transaction_and_permission_is_rechecked(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email="p27-provider@test",
            full_name="P27",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        client = Client(name="Provider phase", status=ClientStatus.active)
        setup.add_all([actor, client])
        await setup.commit()
        actor_id, client_id = actor.id, client.id
    async with AsyncSession(engine, expire_on_commit=False) as session:

        async def collector(*args):
            return facts()

        async def provider(*args):
            assert not session.in_transaction()
            async with AsyncSession(engine) as revoke:
                await revoke.execute(
                    update(User).where(User.id == actor_id).values(is_active=False)
                )
                await revoke.commit()
            return generated()

        with pytest.raises(Exception) as rejected:
            await generate_locked_digest(
                session,
                actor_id=actor_id,
                client_id=client_id,
                period_start=PERIOD[0],
                period_end=PERIOD[1],
                tone=DigestTone.cercano,
                generation_key="permission-recheck-key",
                expected_revision=None,
                require_enabled=False,
                reject_existing=False,
                collector=collector,
                generator=provider,
            )
        assert getattr(rejected.value, "reason", None) == "permission_changed"
        await session.rollback()
    async with AsyncSession(engine) as verify:
        assert (
            await verify.scalar(
                select(func.count(WeeklyDigest.id)).where(
                    WeeklyDigest.client_id == client_id
                )
            )
            == 0
        )


async def test_concurrent_same_key_converges_to_one_row(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email="p27-race@test",
            full_name="Race",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        client = Client(name="Race", status=ClientStatus.active)
        setup.add_all([actor, client])
        await setup.commit()
        actor_id, client_id = actor.id, client.id
    gate = asyncio.Event()
    calls = 0

    async def collector(*args):
        return facts()

    async def provider(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            gate.set()
        await gate.wait()
        return generated()

    async def run():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            digest = await generate_locked_digest(
                session,
                actor_id=actor_id,
                client_id=client_id,
                period_start=PERIOD[0],
                period_end=PERIOD[1],
                tone=DigestTone.cercano,
                generation_key="concurrent-same-key",
                expected_revision=None,
                require_enabled=False,
                reject_existing=False,
                collector=collector,
                generator=provider,
            )
            digest_id = digest.id
            await session.commit()
            return digest_id

    ids = await asyncio.gather(run(), run())
    assert ids[0] == ids[1]
    async with AsyncSession(engine) as verify:
        assert (
            await verify.scalar(
                select(func.count(WeeklyDigest.id)).where(
                    WeeklyDigest.client_id == client_id
                )
            )
            == 1
        )


async def test_generation_rejects_sources_changed_while_provider_runs(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email="p27-facts-change@test",
            full_name="Facts actor",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        client = Client(name="Facts change", status=ClientStatus.active)
        setup.add_all([actor, client])
        await setup.flush()
        task = Task(
            title="Pendiente original",
            client_id=client.id,
            status=TaskStatus.pending,
        )
        setup.add(task)
        await setup.commit()
        actor_id, client_id, task_id = actor.id, client.id, task.id

    async with AsyncSession(engine, expire_on_commit=False) as session:
        async def provider(*args):
            async with AsyncSession(engine) as concurrent:
                await concurrent.execute(
                    update(Task).where(Task.id == task_id).values(title="Pendiente cambiado")
                )
                await concurrent.commit()
            return generated()

        with pytest.raises(Exception) as rejected:
            await generate_locked_digest(
                session,
                actor_id=actor_id,
                client_id=client_id,
                period_start=PERIOD[0],
                period_end=PERIOD[1],
                tone=DigestTone.cercano,
                generation_key="facts-change-generation-key",
                expected_revision=None,
                require_enabled=False,
                reject_existing=False,
                generator=provider,
            )
        assert getattr(rejected.value, "reason", None) == "sources_changed"
        await session.rollback()

    async with AsyncSession(engine) as verify:
        assert (
            await verify.scalar(
                select(func.count(WeeklyDigest.id)).where(
                    WeeklyDigest.client_id == client_id
                )
            )
            == 0
        )


async def test_generation_persists_when_final_source_snapshot_is_stable(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email="p27-facts-stable@test",
            full_name="Stable actor",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        client = Client(name="Facts stable", status=ClientStatus.active)
        setup.add_all([actor, client])
        await setup.flush()
        setup.add(Task(title="Pendiente estable", client_id=client.id, status=TaskStatus.pending))
        await setup.commit()
        actor_id, client_id = actor.id, client.id

    async def provider(*args):
        return generated()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        digest = await generate_locked_digest(
            session,
            actor_id=actor_id,
            client_id=client_id,
            period_start=PERIOD[0],
            period_end=PERIOD[1],
            tone=DigestTone.cercano,
            generation_key="facts-stable-generation-key",
            expected_revision=None,
            require_enabled=False,
            reject_existing=False,
            generator=provider,
        )
        await session.commit()

    async with AsyncSession(engine) as verify:
        assert await verify.scalar(select(func.count(WeeklyDigest.id)).where(WeeklyDigest.id == digest.id)) == 1


def test_source_keys_reject_unknown_duplicate_missing_and_wrong_section():
    base = {"sections": {"done": [], "need": [], "next": [], "metrics": []}}
    catalog = facts()
    for item in (
        {"title": "x", "description": "", "source_keys": []},
        {"title": "x", "description": "", "source_keys": ["missing"]},
        {"title": "x", "description": "", "source_keys": ["task:1", "task:1"]},
        {"title": "x", "description": "", "source_keys": ["aggregate:hours"]},
    ):
        candidate = {"sections": {**base["sections"], "done": [item]}}
        with pytest.raises(ValueError):
            _validate_sources(candidate, catalog)
    assert _validate_sources(generated(), catalog) == generated()


async def test_timeout_is_sanitized_and_persists_nothing(admin_client, db_session):
    from backend.services.digest_generator import DigestProviderError

    client = Client(name="Timeout", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value=facts(),
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            side_effect=DigestProviderError("provider_timeout"),
        ),
    ):
        response = await admin_client.post(
            "/api/digests/generate",
            json={
                "client_id": client.id,
                "period_start": str(PERIOD[0]),
                "period_end": str(PERIOD[1]),
                "generation_key": "provider-timeout-key",
            },
        )
    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "provider_timeout"
    assert (
        await db_session.scalar(
            select(func.count(WeeklyDigest.id)).where(
                WeeklyDigest.client_id == client.id
            )
        )
        == 0
    )


async def test_tone_replay_preserves_source_and_creates_one_version(
    admin_client, db_session, admin_user
):
    source = WeeklyDigest(
        client_id=(await _client(db_session, "Tone replay")).id,
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        tone=DigestTone.cercano,
        content=generated(),
        raw_context={"client_name": "Tone replay"},
        created_by=admin_user.id,
    )
    db_session.add(source)
    await db_session.commit()
    with patch(
        "backend.api.routes.digests.generate_digest_content",
        new_callable=AsyncMock,
        return_value=generated(),
    ) as provider:
        payload = {"tone": "formal", "generation_key": "tone-replay-stable-key"}
        first = await admin_client.put(f"/api/digests/{source.id}", json=payload)
        replay = await admin_client.put(f"/api/digests/{source.id}", json=payload)
    assert first.status_code == replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"] != source.id
    assert provider.await_count == 1
    await db_session.refresh(source)
    assert source.tone == DigestTone.cercano


async def test_tone_generation_rejects_a_source_changed_while_provider_runs(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(
            email="p27-source-change@test",
            full_name="Source actor",
            hashed_password="x",
            role="admin",
            is_active=True,
        )
        client = Client(name="Source changes", status=ClientStatus.active)
        setup.add_all([actor, client])
        await setup.flush()
        source = WeeklyDigest(
            client_id=client.id,
            period_start=PERIOD[0],
            period_end=PERIOD[1],
            tone=DigestTone.cercano,
            content=generated(),
            raw_context=facts(),
            created_by=actor.id,
        )
        setup.add(source)
        await setup.commit()
        source_id, actor_id = source.id, actor.id

    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = await session.get(WeeklyDigest, source_id)

        async def provider(*args):
            changed = generated()
            changed["closing"] = "Cambio concurrente"
            async with AsyncSession(engine) as concurrent:
                await concurrent.execute(
                    update(WeeklyDigest)
                    .where(WeeklyDigest.id == source_id)
                    .values(content=changed)
                )
                await concurrent.commit()
            return generated()

        with pytest.raises(Exception) as rejected:
            await regenerate_digest(
                session,
                actor_id=actor_id,
                source=source,
                tone=DigestTone.formal,
                generation_key="changed-source-generation-key",
                generator=provider,
            )
        assert getattr(rejected.value, "reason", None) == "source_changed"
        await session.rollback()

    async with AsyncSession(engine) as verify:
        assert (
            await verify.scalar(
                select(func.count(WeeklyDigest.id)).where(
                    WeeklyDigest.client_id == client.id
                )
            )
        ) == 1


async def _client(db, name):
    client = Client(name=name, status=ClientStatus.active)
    db.add(client)
    await db.flush()
    return client


async def test_human_edit_drops_provenance_only_from_changed_item(
    admin_client, db_session, admin_user
):
    client = await _client(db_session, "Human edit")
    source = WeeklyDigest(
        client_id=client.id,
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        tone=DigestTone.cercano,
        content=generated(),
        raw_context=facts(),
        created_by=admin_user.id,
    )
    db_session.add(source)
    await db_session.commit()
    edited = generated()
    edited["sections"]["done"][0]["description"] = "Texto humano"
    response = await admin_client.put(
        f"/api/digests/{source.id}", json={"content": edited}
    )
    assert response.status_code == 200, response.text
    assert response.json()["content"]["sections"]["done"][0]["source_keys"] == []
    assert response.json()["content"]["sections"]["metrics"][0]["source_keys"] == [
        "aggregate:hours"
    ]


async def test_human_edit_cannot_spoof_sources_for_unchanged_text(
    admin_client, db_session, admin_user
):
    client = await _client(db_session, "Provenance spoof")
    source = WeeklyDigest(
        client_id=client.id,
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        tone=DigestTone.cercano,
        content=generated(),
        raw_context=facts(),
        created_by=admin_user.id,
    )
    db_session.add(source)
    await db_session.commit()
    spoofed = generated()
    spoofed["sections"]["done"][0]["source_keys"] = ["aggregate:hours"]

    response = await admin_client.put(
        f"/api/digests/{source.id}", json={"content": spoofed}
    )

    assert response.status_code == 200, response.text
    assert response.json()["content"]["sections"]["done"][0]["source_keys"] == [
        "task:1"
    ]


async def test_digest_source_context_obeys_current_module_read_permissions(
    make_member_client, db_session, admin_user
):
    creator = await make_member_client([("digests", True, True), ("tasks", True, False)])
    responsible = await make_member_client([("digests", True, False)])
    try:
        client = Client(name="ACL sources", status=ClientStatus.active)
        db_session.add(client)
        await db_session.flush()
        raw_context = {
            "context_version": 2,
            "projects": [
                {
                    "project_id": 8,
                    "project_name": "Proyecto privado",
                    "resolution": "resolved",
                    "progress_percent": 60,
                    "task_total": 1,
                    "completed_total": 1,
                    "completed_tasks": [{"id": 9, "title": "Tarea privada"}],
                    "in_progress_total": 0,
                    "in_progress_tasks": [],
                    "pending_total": 0,
                    "pending_tasks": [],
                    "total_minutes": 30,
                    "total_hours": 0.5,
                    "historical_template_minutes": 0,
                }
            ],
            "unresolved_projects": [],
            "unassigned": None,
            "pending_followups": [
                {"id": 10, "subject": "Seguimiento privado", "summary": "No visible"}
            ],
            "totals": {"project_count": 1, "task_total": 1, "total_minutes": 30},
            "source_catalog": {
                "task:9": {"kind": "task", "class": "task_completed", "id": 9, "label": "Tarea privada"},
                "project:8": {"kind": "project", "class": "project", "id": 8, "label": "Proyecto privado"},
                "followup:10": {"kind": "followup", "class": "followup", "id": 10, "label": "Seguimiento privado"},
                "aggregate:hours": {"kind": "aggregate", "class": "aggregate", "label": "Tiempo del período"},
            },
            "_generation": {"key": "acl-source-context-key", "actor_id": creator.test_user.id},
        }
        digest = WeeklyDigest(
            client_id=client.id,
            period_start=PERIOD[0],
            period_end=PERIOD[1],
            tone=DigestTone.cercano,
            content={
                **generated(),
                "sections": {
                    **generated()["sections"],
                    "done": [{"title": "Tarea privada", "description": "El texto del informe es visible", "source_keys": ["task:9"]}],
                    "need": [{"title": "Seguimiento privado", "description": "No visible", "source_keys": ["followup:10"]}],
                },
            },
            raw_context=raw_context,
            created_by=creator.test_user.id,
        )
        db_session.add_all([
            ClientReportPolicy(client_id=client.id, responsible_user_id=responsible.test_user.id),
            digest,
        ])
        await db_session.commit()

        creator_detail = await creator.get(f"/api/digests/{digest.id}")
        creator_listed = await creator.get("/api/digests")
        creator_recovered = await creator.get("/api/digests/generation/acl-source-context-key")
        assert creator_detail.status_code == creator_listed.status_code == creator_recovered.status_code == 200
        creator_context = creator_detail.json()["raw_context"]
        assert set(creator_context["source_catalog"]) == {"task:9", "aggregate:hours"}
        assert creator_detail.json()["content"]["sections"]["done"][0]["source_keys"] == ["task:9"]
        assert creator_recovered.json()["content"]["sections"]["done"][0]["source_keys"] == ["task:9"]
        assert creator_detail.json()["content"]["sections"]["need"][0]["source_keys"] == []
        assert creator_context["projects"] == [
            {
                "task_total": 1,
                "completed_total": 1,
                "completed_tasks": [{"id": 9, "title": "Tarea privada"}],
                "in_progress_total": 0,
                "in_progress_tasks": [],
                "pending_total": 0,
                "pending_tasks": [],
                "total_minutes": 30,
                "total_hours": 0.5,
                "historical_template_minutes": 0,
            }
        ]
        listed_digest = next(item for item in creator_listed.json() if item["id"] == digest.id)
        assert listed_digest["raw_context"]["source_catalog"] == creator_context["source_catalog"]

        responsible_detail = await responsible.get(f"/api/digests/{digest.id}")
        responsible_listed = await responsible.get("/api/digests")
        responsible_recovered = await responsible.get("/api/digests/generation/acl-source-context-key")
        assert responsible_detail.status_code == responsible_listed.status_code == 200
        assert responsible_recovered.status_code == 404
        payload = responsible_detail.json()
        context = payload["raw_context"]
        assert set(context["source_catalog"]) == {"aggregate:hours"}
        assert context["projects"] == []
        assert "pending_followups" not in context
        assert context["totals"] == {"project_count": 1}
        assert payload["content"]["sections"]["done"][0]["title"] == "Tarea privada"
        assert payload["content"]["sections"]["done"][0]["source_keys"] == []
        assert payload["content"]["sections"]["need"][0]["source_keys"] == []
        listed_payload = next(item for item in responsible_listed.json() if item["id"] == digest.id)
        assert listed_payload["content"]["sections"]["done"][0]["source_keys"] == []
        assert listed_payload["content"]["sections"]["need"][0]["source_keys"] == []
    finally:
        await creator.aclose()
        await responsible.aclose()
