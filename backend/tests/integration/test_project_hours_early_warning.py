"""Horas del mes: aviso temprano al 75 % para responsable y admins, y arrastre
de horas entre meses (``hours_carryover``) contra Postgres real."""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import (
    Client, Notification, Project, Task, TimeEntry, User, UserPermission, UserRole,
)
from backend.services.incident_project_conditions import (
    PROJECT_MONTHLY_HOURS_EXCEEDED,
    PROJECT_MONTHLY_HOURS_WARNING,
    PROJECT_NO_NEXT_ACTION,
    collect_project_conditions,
    project_visibility_clause,
)
from backend.services.incidents import reconcile_recipient
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 20, 10)  # noqa: DTZ001 - naive UTC, como guarda la app


async def _user(db, *, role=UserRole.member, modules=("projects", "tasks", "timesheet")):
    user = User(email=f"hours-{uuid4().hex}@test.local", full_name="Persona", hashed_password="x",
                role=role, is_active=True)
    db.add(user)
    await db.flush()
    db.add_all([UserPermission(user_id=user.id, module=m, can_read=True, can_write=True) for m in modules])
    await db.flush()
    return user


async def _project(db, owner_id, **fields):
    client = Client(name=f"Cliente {uuid4().hex[:6]}")
    db.add(client)
    await db.flush()
    project = Project(name=fields.pop("name", "SEO mensual"), client_id=client.id, owner_id=owner_id,
                      is_recurring=True, monthly_hours_budget=10, **fields)
    db.add(project)
    await db.flush()
    task = Task(title="Trabajo", client_id=client.id, project_id=project.id)
    db.add(task)
    await db.flush()
    return project, task


async def _log(db, task, user, minutes, day):
    db.add(TimeEntry(task_id=task.id, user_id=user.id, minutes=minutes, date=datetime.combine(day, datetime.min.time())))
    await db.flush()


def _kinds(conditions, project_id):
    return {c.kind for c in conditions.values() if c.entity_id == project_id}


async def test_aviso_temprano_al_75(db_session):
    owner = await _user(db_session)
    project, task = await _project(db_session, owner.id, start_date=datetime(2026, 1, 1))  # noqa: DTZ001
    await _log(db_session, task, owner, 420, date(2026, 9, 3))  # 7 h de 10: 70 %
    assert PROJECT_MONTHLY_HOURS_WARNING not in _kinds(await collect_project_conditions(db_session, owner.id, NOW), project.id)

    await _log(db_session, task, owner, 30, date(2026, 9, 4))  # 7,5 h: 75 %
    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    warning = next(c for c in conditions.values() if c.kind == PROJECT_MONTHLY_HOURS_WARNING)
    assert warning.key == f"{PROJECT_MONTHLY_HOURS_WARNING}:project:{project.id}:2026-09"
    assert "75%" in warning.title and "Aviso temprano" in warning.message


async def test_los_admins_reciben_las_horas_del_mes_de_proyectos_ajenos(db_session):
    owner = await _user(db_session)
    admin = await _user(db_session, role=UserRole.admin, modules=())
    project, task = await _project(db_session, owner.id, start_date=datetime(2026, 1, 1))  # noqa: DTZ001
    await _log(db_session, task, owner, 480, date(2026, 9, 3))
    orphan, orphan_task = await _project(db_session, None, name="Sin responsable", start_date=datetime(2026, 1, 1))  # noqa: DTZ001
    await _log(db_session, orphan_task, owner, 660, date(2026, 9, 3))

    for_admin = await collect_project_conditions(db_session, admin.id, NOW)
    assert _kinds(for_admin, project.id) == {PROJECT_MONTHLY_HOURS_WARNING}
    assert _kinds(for_admin, orphan.id) == {PROJECT_MONTHLY_HOURS_EXCEEDED}
    # Lo demás (próxima acción, cierres) sigue siendo sólo del responsable.
    assert PROJECT_NO_NEXT_ACTION in _kinds(await collect_project_conditions(db_session, owner.id, NOW), project.id)

    # La misma clave para los dos: un descarte del admin no toca el del responsable.
    for user in (admin, owner):
        await reconcile_recipient(db_session, user.id, now=NOW)
    await db_session.flush()
    rows = (await db_session.scalars(select(Notification).where(
        Notification.type == PROJECT_MONTHLY_HOURS_WARNING, Notification.entity_id == project.id,
    ))).all()
    assert {r.user_id for r in rows} == {admin.id, owner.id}
    assert len({r.dedupe_key for r in rows}) == 1
    visible = await db_session.scalar(select(Notification.id).where(
        Notification.user_id == admin.id, Notification.entity_id == project.id,
        project_visibility_clause(admin.id, current_only=True, now=NOW),
    ))
    assert visible is not None

    # Un miembro que no lleva el proyecto no lo recibe.
    other = await _user(db_session)
    assert not _kinds(await collect_project_conditions(db_session, other.id, NOW), project.id)


async def test_arrastre_de_horas_sobrantes_y_de_exceso(db_session):
    owner = await _user(db_session)
    spare, spare_task = await _project(db_session, owner.id, name="Sobran", hours_carryover=True,
                                       start_date=datetime(2026, 7, 1))  # noqa: DTZ001
    await _log(db_session, spare_task, owner, 360, date(2026, 8, 20))   # agosto: 6 h de 10 → sobran 4
    await _log(db_session, spare_task, owner, 600, date(2026, 9, 10))   # septiembre: 10 h de 14 = 71 %

    excess, excess_task = await _project(db_session, owner.id, name="Exceso", hours_carryover=True,
                                         start_date=datetime(2026, 7, 1))  # noqa: DTZ001
    await _log(db_session, excess_task, owner, 840, date(2026, 8, 20))  # agosto: 14 h → 4 de exceso
    await _log(db_session, excess_task, owner, 300, date(2026, 9, 10))  # septiembre: 5 h de 6 = 83 %

    plain, plain_task = await _project(db_session, owner.id, name="Sin arrastre",
                                       start_date=datetime(2026, 7, 1))  # noqa: DTZ001
    await _log(db_session, plain_task, owner, 360, date(2026, 8, 20))
    await _log(db_session, plain_task, owner, 600, date(2026, 9, 10))   # 10 de 10 = 100 %

    new, new_task = await _project(db_session, owner.id, name="Nuevo", hours_carryover=True,
                                   start_date=datetime(2026, 9, 1))  # noqa: DTZ001
    await _log(db_session, new_task, owner, 600, date(2026, 9, 10))     # sin mes anterior: 10 de 10

    conditions = await collect_project_conditions(db_session, owner.id, NOW)
    assert not {PROJECT_MONTHLY_HOURS_WARNING, PROJECT_MONTHLY_HOURS_EXCEEDED} & _kinds(conditions, spare.id)
    warning = next(c for c in conditions.values() if c.entity_id == excess.id and c.kind == PROJECT_MONTHLY_HOURS_WARNING)
    assert "Presupuesto del mes: 6h (10h − 4h de exceso el mes anterior)" in warning.message
    assert PROJECT_MONTHLY_HOURS_EXCEEDED in _kinds(conditions, plain.id)
    assert PROJECT_MONTHLY_HOURS_EXCEEDED in _kinds(conditions, new.id)

    # La comprobación en SQL (bandeja) da lo mismo que el cálculo en Python.
    await reconcile_recipient(db_session, owner.id, now=NOW)
    await db_session.flush()
    live = set((await db_session.execute(select(Notification.entity_id, Notification.type).where(
        Notification.user_id == owner.id,
        Notification.type.in_((PROJECT_MONTHLY_HOURS_WARNING, PROJECT_MONTHLY_HOURS_EXCEEDED)),
        project_visibility_clause(owner.id, current_only=True, now=NOW),
    ))).all())
    assert live == {
        (excess.id, PROJECT_MONTHLY_HOURS_WARNING),
        (plain.id, PROJECT_MONTHLY_HOURS_EXCEEDED),
        (new.id, PROJECT_MONTHLY_HOURS_EXCEEDED),
    }


async def test_ficha_ciclo_y_extension_enseñan_el_arrastre(admin_client, admin_user, db_session):
    today = business_today()
    month_start = today.replace(day=1)
    previous_day = month_start - timedelta(days=3)
    project, task = await _project(db_session, admin_user.id, hours_carryover=True,
                                   start_date=datetime.combine(previous_day.replace(day=1), datetime.min.time()))
    await _log(db_session, task, admin_user, 480, previous_day)  # mes anterior: 8 h de 10 → sobran 2
    await _log(db_session, task, admin_user, 60, month_start)
    await db_session.commit()

    detail = (await admin_client.get(f"/api/projects/{project.id}")).json()
    assert detail["hours_carryover"] is True
    assert detail["effective_monthly_hours_budget"] == 10
    assert detail["month_hours_budget"] == 12 and detail["month_hours_carried"] == 2

    cycle = (await admin_client.get(f"/api/projects/{project.id}/monthly-cycle")).json()
    assert (cycle["budget_hours"], cycle["base_budget_hours"], cycle["carried_hours"]) == (12, 10, 2)
    assert cycle["remaining_hours"] == 11

    timer = (await admin_client.get(f"/api/timer/project-budget/{project.id}")).json()
    assert timer["month"]["budget_hours"] == 12 and timer["month"]["carried_hours"] == 2

    # Apagarlo vuelve al techo de siempre; null no se acepta.
    assert (await admin_client.put(f"/api/projects/{project.id}", json={"hours_carryover": None})).status_code == 422
    off = (await admin_client.put(f"/api/projects/{project.id}", json={"hours_carryover": False})).json()
    assert off["hours_carryover"] is False
    detail = (await admin_client.get(f"/api/projects/{project.id}")).json()
    assert detail["month_hours_budget"] == 10 and detail["month_hours_carried"] is None
