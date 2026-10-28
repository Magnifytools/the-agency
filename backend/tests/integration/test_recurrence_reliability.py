"""Recurrencia fiable: recuperar días que el job no corrió, festivos de quien
lleva la plantilla y reglas nuevas (varios días, trimestral, último hábil)."""
from datetime import date

import pytest
from sqlalchemy import select

from backend.db.models import CompanyHoliday, Task, TaskRecurrenceOccurrence
from backend.services.recurrence import generate_recurring_instances

pytestmark = pytest.mark.integration

MONDAY = date(2031, 3, 3)
FRIDAY = date(2031, 3, 7)


async def _template(admin_client, db_session, since: date | None, **rule) -> Task:
    response = await admin_client.post("/api/tasks", json={
        "title": f"Plantilla {rule['recurrence_pattern']}", "is_recurring": True, **rule,
    })
    assert response.status_code == 201, response.text
    template = await db_session.get(Task, response.json()["id"])
    template.recurrence_since = since
    await db_session.commit()
    return template


async def _children(db_session, template_id: int) -> list[Task]:
    return list((await db_session.execute(select(Task).where(
        Task.recurring_parent_id == template_id,
    ).order_by(Task.recurrence_occurrence_date))).scalars())


async def test_missed_days_are_recovered_but_never_before_the_floor(admin_client, db_session):
    template = await _template(admin_client, db_session, MONDAY + date.resolution * 1,
                               recurrence_pattern="daily")
    # El job no corrió en toda la semana: el viernes recupera martes a jueves.
    assert await generate_recurring_instances(db_session, target_date=FRIDAY) == 4
    children = await _children(db_session, template.id)
    assert [child.recurrence_occurrence_date for child in children] == [
        date(2031, 3, 4), date(2031, 3, 5), date(2031, 3, 6), FRIDAY,
    ]
    # Cada una con su día: las recuperadas salen como pendientes de días anteriores.
    assert [child.scheduled_date for child in children] == [c.recurrence_occurrence_date for c in children]
    assert await generate_recurring_instances(db_session, target_date=FRIDAY) == 0


async def test_templates_without_floor_only_create_today(admin_client, db_session):
    template = await _template(admin_client, db_session, None, recurrence_pattern="daily")
    assert await generate_recurring_instances(db_session, target_date=FRIDAY) == 1
    assert [c.recurrence_occurrence_date for c in await _children(db_session, template.id)] == [FRIDAY]


async def test_holidays_of_the_assignee_move_the_work_day(admin_client, db_session):
    admin = admin_client.test_user
    admin.region = "TST"
    db_session.add(CompanyHoliday(date=MONDAY + date.resolution * 7, name="Festivo de prueba", region="TST"))
    await db_session.commit()
    template = await _template(admin_client, db_session, date(2031, 3, 8), recurrence_pattern="weekly",
                               recurrence_day=0, assigned_to=admin.id)
    monday_holiday = date(2031, 3, 10)
    assert await generate_recurring_instances(db_session, target_date=monday_holiday) == 0
    assert await generate_recurring_instances(db_session, target_date=date(2031, 3, 11)) == 1
    child = (await _children(db_session, template.id))[-1]
    assert child.recurrence_occurrence_date == monday_holiday
    assert child.scheduled_date == date(2031, 3, 11)

    task = (await admin_client.get(f"/api/tasks/{template.id}")).json()
    preview = await admin_client.post("/api/tasks/recurrence-preview", json={
        "is_recurring": True, "recurrence_pattern": "weekly", "recurrence_day": 0,
        "assigned_to": admin.id,
    })
    assert preview.status_code == 200, preview.text
    assert task["recurrence_summary"]["label"] == "Cada lunes"


async def test_a_month_day_on_the_weekend_is_created_on_monday(admin_client, db_session):
    template = await _template(admin_client, db_session, MONDAY, recurrence_pattern="monthly",
                               recurrence_day=15)
    assert await generate_recurring_instances(db_session, target_date=date(2031, 3, 14)) == 0
    assert await generate_recurring_instances(db_session, target_date=date(2031, 3, 17)) == 1
    child = (await _children(db_session, template.id))[0]
    assert (child.recurrence_occurrence_date, child.scheduled_date) == (date(2031, 3, 15), date(2031, 3, 17))


async def test_two_dates_on_one_work_day_are_one_task_with_two_receipts(admin_client, db_session):
    admin = admin_client.test_user
    admin.region = "TST"
    db_session.add(CompanyHoliday(date=date(2031, 3, 10), name="Festivo de prueba", region="TST"))
    await db_session.commit()
    template = await _template(admin_client, db_session, date(2031, 3, 8), recurrence_pattern="weekdays",
                               recurrence_weekdays=[1, 0], assigned_to=admin.id)
    assert template.recurrence_weekdays == [0, 1]
    assert await generate_recurring_instances(db_session, target_date=date(2031, 3, 11)) == 1
    receipts = list((await db_session.execute(select(TaskRecurrenceOccurrence.date).where(
        TaskRecurrenceOccurrence.template_id == template.id,
    ).order_by(TaskRecurrenceOccurrence.date))).scalars())
    assert receipts == [date(2031, 3, 10), date(2031, 3, 11)]
    assert len(await _children(db_session, template.id)) == 1


async def test_new_rules_validate_and_weekdays_are_only_kept_for_their_rule(admin_client, db_session):
    bad = await admin_client.post("/api/tasks", json={
        "title": "Sin días", "is_recurring": True, "recurrence_pattern": "weekdays", "recurrence_weekdays": [],
    })
    assert bad.status_code == 422
    created = await admin_client.post("/api/tasks", json={
        "title": "Varios días", "is_recurring": True, "recurrence_pattern": "weekdays",
        "recurrence_weekdays": [3, 1],
    })
    assert created.status_code == 201, created.text
    assert created.json()["recurrence_weekdays"] == [1, 3]
    assert created.json()["recurrence_summary"]["label"] == "Cada martes y jueves"
    changed = await admin_client.put(f"/api/tasks/{created.json()['id']}", json={
        "recurrence_pattern": "last_business_day",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["recurrence_weekdays"] is None
    quarterly = await admin_client.post("/api/tasks", json={
        "title": "Trimestral", "is_recurring": True, "recurrence_pattern": "quarterly", "recurrence_day": 31,
    })
    assert quarterly.status_code == 422


async def test_rule_change_and_resume_move_the_floor(admin_client, db_session):
    template = await _template(admin_client, db_session, date(2020, 1, 1), recurrence_pattern="daily")
    await admin_client.put(f"/api/tasks/{template.id}", json={"title": "Sólo el título"})
    await db_session.refresh(template)
    assert template.recurrence_since == date(2020, 1, 1)
    await admin_client.put(f"/api/tasks/{template.id}", json={"recurrence_paused": True})
    await admin_client.put(f"/api/tasks/{template.id}", json={"recurrence_paused": False})
    await db_session.refresh(template)
    assert template.recurrence_since == date.today()
