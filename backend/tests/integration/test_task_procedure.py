"""Procedures in recurring tasks: the template holds the "how", each
occurrence receives its own copy and a fresh checklist."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.db.models import ChangeLog, Task, TaskChecklist
from backend.services.recurrence import generate_recurring_instances

pytestmark = pytest.mark.integration

MONDAY = date(2026, 9, 21)


async def _template(admin_client, **extra):
    response = await admin_client.post("/api/tasks", json={
        "title": "Informe mensual", "is_recurring": True,
        "recurrence_pattern": "weekly", "recurrence_day": 0,
        "procedure_text": "1. Exportar Search Console\n2. Revisar caídas",
        "procedure_url": "https://docs.example.test/informe",
        **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _children(db_session, template_id):
    db_session.expire_all()
    return list((await db_session.execute(
        select(Task).where(Task.recurring_parent_id == template_id).order_by(Task.id)
    )).scalars())


async def _checklist(db_session, task_id):
    return list((await db_session.execute(
        select(TaskChecklist).where(TaskChecklist.task_id == task_id)
        .order_by(TaskChecklist.order_index, TaskChecklist.id)
    )).scalars())


async def test_occurrence_copies_procedure_and_starts_with_fresh_checklist(
    admin_client, db_session,
):
    template = await _template(admin_client)
    assert template["procedure_text"].startswith("1. Exportar")
    tid = template["id"]
    first = await admin_client.post(f"/api/tasks/{tid}/checklist", json={
        "text": "Exportar datos", "order_index": 0, "due_date": "2026-09-01",
    })
    second = await admin_client.post(f"/api/tasks/{tid}/checklist", json={
        "text": "Enviar al cliente", "order_index": 1,
    })
    assert first.status_code == second.status_code == 201
    # A tick on the template must not leak into the occurrences.
    ticked = await admin_client.put(
        f"/api/tasks/{tid}/checklist/{first.json()['id']}", json={"is_done": True},
    )
    assert ticked.status_code == 200, ticked.text

    assert await generate_recurring_instances(db_session, target_date=MONDAY) == 1
    [child] = await _children(db_session, tid)
    assert child.procedure_text == template["procedure_text"]
    assert child.procedure_url == "https://docs.example.test/informe"
    items = await _checklist(db_session, child.id)
    assert [(i.text, i.is_done, i.due_date) for i in items] == [
        ("Exportar datos", False, None), ("Enviar al cliente", False, None),
    ]
    detail = await admin_client.get(f"/api/tasks/{child.id}")
    assert detail.json()["procedure_url"] == "https://docs.example.test/informe"
    assert detail.json()["checklist_count"] == 2

    # Editing the template changes future occurrences only.
    edited = await admin_client.put(f"/api/tasks/{tid}", json={
        "procedure_text": "1. Nuevo paso", "procedure_url": None,
    })
    assert edited.status_code == 200, edited.text
    await admin_client.post(f"/api/tasks/{tid}/checklist", json={
        "text": "Archivar", "order_index": 2,
    })
    assert await generate_recurring_instances(
        db_session, target_date=MONDAY + timedelta(days=7),
    ) == 1
    old, new = await _children(db_session, tid)
    assert old.procedure_text.startswith("1. Exportar")
    assert old.procedure_url == "https://docs.example.test/informe"
    assert len(await _checklist(db_session, old.id)) == 2
    assert new.procedure_text == "1. Nuevo paso"
    assert new.procedure_url is None
    assert [i.text for i in await _checklist(db_session, new.id)] == [
        "Exportar datos", "Enviar al cliente", "Archivar",
    ]


async def test_procedure_is_written_only_on_the_template(admin_client, db_session):
    plain = await admin_client.post("/api/tasks", json={
        "title": "Puntual", "procedure_text": "Pasos",
    })
    assert plain.status_code == 422
    unsafe = await admin_client.post("/api/tasks", json={
        "title": "Plantilla", "is_recurring": True, "recurrence_pattern": "daily",
        "procedure_url": "javascript:alert(1)",
    })
    assert unsafe.status_code == 422

    template = await _template(admin_client)
    assert await generate_recurring_instances(db_session, target_date=MONDAY) == 1
    [child] = await _children(db_session, template["id"])
    changed = await admin_client.put(f"/api/tasks/{child.id}", json={"procedure_text": "Otro"})
    assert changed.status_code == 422
    # The panel sends the whole form: unchanged values are accepted.
    same = await admin_client.put(f"/api/tasks/{child.id}", json={
        "title": "Informe de esta semana",
        "procedure_text": child.procedure_text, "procedure_url": child.procedure_url,
    })
    assert same.status_code == 200, same.text
    assert same.json()["procedure_text"] == child.procedure_text

    blank = await admin_client.put(f"/api/tasks/{template['id']}", json={
        "procedure_text": "   ",
    })
    assert blank.status_code == 200
    assert blank.json()["procedure_text"] is None


async def test_procedure_edit_is_undoable(admin_client, db_session):
    template = await _template(admin_client)
    before = set((await db_session.scalars(select(ChangeLog.id))).all())
    edited = await admin_client.put(f"/api/tasks/{template['id']}", json={
        "procedure_text": "Versión nueva",
    })
    assert edited.status_code == 200, edited.text
    change = await db_session.scalar(
        select(ChangeLog).where(ChangeLog.id.notin_(before)).order_by(ChangeLog.id.desc())
    )
    assert change is not None and change.entity_type == "task"
    undone = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert undone.status_code == 200, undone.text
    restored = await admin_client.get(f"/api/tasks/{template['id']}")
    assert restored.json()["procedure_text"] == template["procedure_text"]
