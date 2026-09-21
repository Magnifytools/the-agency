from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException

from backend.db.models import Task, TaskStatus, User, UserRole
from backend.services.task_lifecycle import validate_task_waiting
from backend.services.temporal import business_today


pytestmark = pytest.mark.integration


async def _task(db_session, user_id: int, **overrides) -> Task:
    values = {
        "title": "Tarea de espera",
        "status": TaskStatus.pending,
        "assigned_to": user_id,
    }
    values.update(overrides)
    task = Task(**values)
    db_session.add(task)
    await db_session.flush()
    return task


async def test_enter_waiting_normalizes_reason_and_requires_future_review(
    db_session, admin_user,
):
    task = await _task(db_session, admin_user.id)
    data = {
        "status": TaskStatus.waiting,
        "waiting_for": "  Respuesta del cliente  ",
        "follow_up_date": business_today() + timedelta(days=1),
    }

    await validate_task_waiting(db_session, data, existing=task)

    assert data == {
        "status": TaskStatus.waiting,
        "waiting_for": "Respuesta del cliente",
        "follow_up_date": business_today() + timedelta(days=1),
    }

    without_review_date = {
        "status": TaskStatus.waiting,
        "waiting_for": "Proveedor",
    }
    with pytest.raises(HTTPException) as error:
        await validate_task_waiting(db_session, without_review_date, existing=task)
    assert error.value.status_code == 422


async def test_enter_waiting_requires_reason_active_owner_and_rejects_past_date(
    db_session, admin_user,
):
    inactive = User(
        email="inactive-waiting@test.local", full_name="Inactive Waiting",
        hashed_password="unused", role=UserRole.member, is_active=False,
    )
    db_session.add(inactive)
    await db_session.flush()
    task = await _task(db_session, admin_user.id)

    invalid_patches = [
        {"status": TaskStatus.waiting, "waiting_for": "   "},
        {
            "status": TaskStatus.waiting, "waiting_for": "Cliente",
            "assigned_to": inactive.id,
        },
        {
            "status": TaskStatus.waiting, "waiting_for": "Cliente",
            "follow_up_date": business_today() - timedelta(days=1),
        },
    ]
    for patch in invalid_patches:
        with pytest.raises(HTTPException) as error:
            await validate_task_waiting(db_session, patch, existing=task)
        assert error.value.status_code == 422


async def test_unrelated_edit_preserves_incomplete_legacy_waiting_row(
    db_session, admin_user,
):
    task = await _task(
        db_session, admin_user.id, status=TaskStatus.waiting,
        waiting_for=None, follow_up_date=None,
    )
    data = {"title": "Corrección editorial"}

    await validate_task_waiting(db_session, data, existing=task)

    assert data == {"title": "Corrección editorial"}

    full_draft = {
        "title": "Otra corrección editorial",
        "status": TaskStatus.waiting,
        "waiting_for": None,
        "follow_up_date": None,
        "assigned_to": admin_user.id,
    }
    await validate_task_waiting(db_session, full_draft, existing=task)
    assert full_draft["title"] == "Otra corrección editorial"

    with pytest.raises(HTTPException) as error:
        await validate_task_waiting(
            db_session, {"waiting_for": "Cliente"}, existing=task,
        )
    assert error.value.status_code == 422


async def test_updating_wait_fields_validates_only_new_date(
    db_session, admin_user,
):
    task = await _task(
        db_session, admin_user.id, status=TaskStatus.waiting,
        waiting_for="Cliente", follow_up_date=business_today() - timedelta(days=2),
    )
    reason_only = {"waiting_for": "  Legal  "}
    await validate_task_waiting(db_session, reason_only, existing=task)
    assert reason_only == {"waiting_for": "Legal"}

    full_patch_with_same_expired_date = {
        "waiting_for": "  Compras  ",
        "follow_up_date": task.follow_up_date,
        "assigned_to": admin_user.id,
    }
    await validate_task_waiting(
        db_session, full_patch_with_same_expired_date, existing=task,
    )
    assert full_patch_with_same_expired_date["waiting_for"] == "Compras"

    changed_date = {"follow_up_date": business_today() - timedelta(days=1)}
    with pytest.raises(HTTPException) as error:
        await validate_task_waiting(db_session, changed_date, existing=task)
    assert error.value.status_code == 422

    historical_restore = {"follow_up_date": business_today() - timedelta(days=1)}
    await validate_task_waiting(
        db_session, historical_restore, existing=task, allow_past_date=True,
    )
    assert historical_restore["follow_up_date"] < business_today()


async def test_leaving_waiting_clears_fields_despite_contradictory_payload(
    db_session, admin_user,
):
    task = await _task(
        db_session, admin_user.id, status=TaskStatus.waiting,
        waiting_for="Cliente", follow_up_date=business_today(),
    )
    data = {
        "status": TaskStatus.in_progress,
        "waiting_for": "No debe sobrevivir",
        "follow_up_date": business_today() + timedelta(days=3),
    }

    await validate_task_waiting(db_session, data, existing=task)

    assert data["waiting_for"] is None
    assert data["follow_up_date"] is None


async def test_task_api_applies_waiting_normalization_and_forced_cleanup(
    admin_client, db_session,
):
    task = await _task(db_session, admin_client.test_user.id)
    review_date = business_today() + timedelta(days=2)

    waiting = await admin_client.put(f"/api/tasks/{task.id}", json={
        "status": "waiting",
        "waiting_for": "  Confirmación externa  ",
        "follow_up_date": review_date.isoformat(),
    })
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["waiting_for"] == "Confirmación externa"
    assert waiting.json()["follow_up_date"] == review_date.isoformat()

    resumed = await admin_client.put(f"/api/tasks/{task.id}", json={
        "status": "in_progress",
        "waiting_for": "No debe sobrevivir",
        "follow_up_date": review_date.isoformat(),
    })
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["waiting_for"] is None
    assert resumed.json()["follow_up_date"] is None


async def test_task_api_full_draft_preserves_legacy_waiting_metadata(
    admin_client, db_session,
):
    incomplete = await _task(
        db_session, admin_client.test_user.id,
        status=TaskStatus.waiting, waiting_for=None, follow_up_date=None,
    )
    edited = await admin_client.put(f"/api/tasks/{incomplete.id}", json={
        "title": "Título corregido",
        "status": "waiting",
        "waiting_for": None,
        "follow_up_date": None,
        "assigned_to": admin_client.test_user.id,
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Título corregido"
    assert edited.json()["waiting_for"] is None
    assert edited.json()["follow_up_date"] is None

    expired = business_today() - timedelta(days=2)
    waiting = await _task(
        db_session, admin_client.test_user.id,
        status=TaskStatus.waiting, waiting_for="Cliente", follow_up_date=expired,
    )
    reason_changed = await admin_client.put(f"/api/tasks/{waiting.id}", json={
        "status": "waiting",
        "waiting_for": "  Compras  ",
        "follow_up_date": expired.isoformat(),
        "assigned_to": admin_client.test_user.id,
    })
    assert reason_changed.status_code == 200, reason_changed.text
    assert reason_changed.json()["waiting_for"] == "Compras"
    assert reason_changed.json()["follow_up_date"] == expired.isoformat()


async def test_task_api_requires_active_assignee_without_rewriting_legacy_assignments(
    admin_client, db_session,
):
    inactive = User(
        email="inactive-assignee@test.local", full_name="Inactive Assignee",
        hashed_password="unused", role=UserRole.member, is_active=False,
    )
    db_session.add(inactive)
    await db_session.flush()
    assigned = await _task(db_session, admin_client.test_user.id, title="Reasignable")
    legacy = await _task(db_session, inactive.id, title="Asignación histórica")
    await db_session.commit()

    created = await admin_client.post("/api/tasks", json={
        "title": "Alta a persona inactiva", "assigned_to": inactive.id,
    })
    assert created.status_code == 422, created.text
    assert "inactiva" in created.json()["detail"]

    reassigned = await admin_client.put(f"/api/tasks/{assigned.id}", json={
        "assigned_to": inactive.id,
    })
    assert reassigned.status_code == 422, reassigned.text
    await db_session.refresh(assigned)
    assert assigned.assigned_to == admin_client.test_user.id

    bulk = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": [assigned.id], "updates": {"assigned_to": inactive.id},
    })
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["updated"] == 0
    assert bulk.json()["failed"] == 1
    await db_session.refresh(assigned)
    assert assigned.assigned_to == admin_client.test_user.id

    unassigned = await admin_client.put(f"/api/tasks/{assigned.id}", json={
        "assigned_to": None,
    })
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["assigned_to"] is None

    legacy_edit = await admin_client.put(f"/api/tasks/{legacy.id}", json={
        "title": "Asignación histórica corregida",
        "assigned_to": inactive.id,
    })
    assert legacy_edit.status_code == 200, legacy_edit.text
    assert legacy_edit.json()["assigned_to"] == inactive.id


async def test_starting_timer_uses_lifecycle_stamp_for_advanced_task(
    admin_client, db_session,
):
    task = await _task(
        db_session, admin_client.test_user.id,
        status=TaskStatus.advanced, advanced_at=business_today(),
    )

    response = await admin_client.post("/api/timer/start", json={"task_id": task.id})

    assert response.status_code == 201, response.text
    await db_session.refresh(task)
    assert task.status == TaskStatus.in_progress
    assert task.advanced_at is None
