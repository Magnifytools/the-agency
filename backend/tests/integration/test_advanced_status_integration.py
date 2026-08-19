"""Integración: el estado "Avanzada" contra PostgreSQL real.

"Avanzada" significa *hoy he avanzado en esto, mañana sigo*: cierra la tarea en
el informe diario del día pero vuelve sola a "En curso" al día siguiente. Tres
piezas que la suite mockeada no puede ver, porque ahí no se ejecuta SQL:

  1. El **tipo enum de Postgres** tiene que conocer el valor nuevo. Un
     ``ALTER TYPE`` olvidado es exactamente lo que pasó con ``vattreatment``,
     que hubo que parchear a mano en producción.
  2. La **barrida nocturna** tiene que devolver a ``in_progress`` las avanzadas
     de días anteriores y **no** tocar las de hoy.
  3. El **prefill del daily** tiene que incluirlas sin depender del timer.
"""

from __future__ import annotations

import enum as _enum
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

from backend.db.models import Client, Task, TaskStatus


# ── 1. El enum de Postgres ───────────────────────────────────────────

async def _pg_enum_labels(db_session, type_name: str) -> set[str]:
    result = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :t"
        ),
        {"t": type_name},
    )
    return {row[0] for row in result}


@pytest.mark.asyncio
async def test_el_tipo_taskstatus_conoce_advanced(db_session):
    assert "advanced" in await _pg_enum_labels(db_session, "taskstatus")


@pytest.mark.asyncio
async def test_todos_los_enums_del_orm_estan_completos_en_pg(db_session):
    """Ningún tipo enum existente puede tener menos valores que su clase Python.

    Este es el invariante que faltaba: ``_ensure_pg_enums`` solo crea tipos que
    no existen, así que un valor añadido a un enum ya desplegado se quedaba
    fuera y reventaba en el primer INSERT.
    """
    from backend.db import models as _models

    faltantes: dict[str, set[str]] = {}
    for obj in vars(_models).values():
        if not (isinstance(obj, type) and issubclass(obj, _enum.Enum) and obj is not _enum.Enum):
            continue
        labels = await _pg_enum_labels(db_session, obj.__name__.lower())
        if not labels:
            continue  # el tipo no existe en PG (columnas native_enum=False)
        ausentes = {m.name for m in obj} - labels
        if ausentes:
            faltantes[obj.__name__] = ausentes

    assert not faltantes, f"valores de enum ausentes en Postgres: {faltantes}"


@pytest.mark.asyncio
async def test_ensure_enum_values_anade_valores_a_un_tipo_ya_existente(engine, monkeypatch):
    """Prueba del mecanismo: tipo ya creado al que le falta un valor nuevo.

    Reproduce el fallo de ``vattreatment``: se crea el tipo con un solo valor,
    se le añade un miembro a la clase Python y la migración debe alcanzarlo.
    """
    import backend.db.database as db_module
    from backend.db import models as _models
    from backend.startup import migrations as mig

    class _EnumDePrueba(str, _enum.Enum):
        viejo = "viejo"
        nuevo = "nuevo"

    type_name = "_enumdeprueba"
    _EnumDePrueba.__name__ = "_EnumDePrueba"

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TYPE IF EXISTS {type_name}"))
        # El tipo nace SIN 'nuevo', como un despliegue anterior.
        await conn.execute(text(f"CREATE TYPE {type_name} AS ENUM ('viejo')"))

    monkeypatch.setattr(_models, "_EnumDePrueba", _EnumDePrueba, raising=False)
    monkeypatch.setattr(db_module, "engine", engine)
    try:
        await mig._ensure_enum_values()

        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t "
                    "ON t.oid = e.enumtypid WHERE t.typname = :t"
                ),
                {"t": type_name},
            )
            labels = {row[0] for row in result}
        assert labels == {"viejo", "nuevo"}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TYPE IF EXISTS {type_name}"))


# ── 2 y 3. Ciclo completo: marcar → daily → barrida ─────────────────

async def _crear_tarea(db_session, user_id: int, *, status=TaskStatus.in_progress, advanced_at=None):
    client = Client(name="Cliente avanzada")
    db_session.add(client)
    await db_session.flush()

    task = Task(
        title="Auditoría técnica a medias",
        client_id=client.id,
        assigned_to=user_id,
        status=status,
        advanced_at=advanced_at,
    )
    db_session.add(task)
    await db_session.flush()
    return task


def _sesion_de_prueba(monkeypatch, db_session):
    """Hace que los jobs de fondo usen la sesión transaccional del test."""
    import backend.db.database as db_module

    class _Shim:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_module, "async_session", lambda: _Shim())


@pytest.mark.asyncio
async def test_marcar_avanzada_sella_la_fecha(admin_client, db_session):
    task = await _crear_tarea(db_session, admin_client.test_user.id)

    resp = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "advanced"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "advanced"

    await db_session.refresh(task)
    assert task.advanced_at == date.today()


@pytest.mark.asyncio
async def test_crear_la_tarea_ya_en_avanzada_sella_la_fecha(admin_client, db_session):
    """Sin esto, la barrida nocturna la trataría como huérfana y la revertiría
    el mismo día en que se creó."""
    resp = await admin_client.post(
        "/api/tasks", json={"title": "Nace avanzada", "status": "advanced"}
    )
    assert resp.status_code == 201, resp.text

    task = (await db_session.execute(
        select(Task).where(Task.id == resp.json()["id"])
    )).scalar_one()
    assert task.advanced_at == date.today()


@pytest.mark.asyncio
async def test_volver_a_otro_estado_limpia_la_fecha(admin_client, db_session):
    task = await _crear_tarea(
        db_session, admin_client.test_user.id,
        status=TaskStatus.advanced, advanced_at=date.today(),
    )

    resp = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "completed"})
    assert resp.status_code == 200, resp.text

    await db_session.refresh(task)
    assert task.advanced_at is None


@pytest.mark.asyncio
async def test_la_barrida_devuelve_a_en_curso_las_de_ayer(db_session, admin_user, monkeypatch):
    from backend.startup.background_tasks import _reset_advanced_tasks

    ayer = await _crear_tarea(
        db_session, admin_user.id,
        status=TaskStatus.advanced, advanced_at=date.today() - timedelta(days=1),
    )
    hoy = await _crear_tarea(
        db_session, admin_user.id,
        status=TaskStatus.advanced, advanced_at=date.today(),
    )

    _sesion_de_prueba(monkeypatch, db_session)
    await _reset_advanced_tasks()

    await db_session.refresh(ayer)
    await db_session.refresh(hoy)

    assert ayer.status == TaskStatus.in_progress, "la avanzada de ayer debe volver a En curso"
    assert ayer.advanced_at is None
    assert hoy.status == TaskStatus.advanced, "la avanzada de hoy no se toca hasta mañana"


@pytest.mark.asyncio
async def test_la_barrida_recupera_avanzadas_sin_fecha(db_session, admin_user, monkeypatch):
    """Tarea marcada antes de existir ``advanced_at`` (o por SQL a mano)."""
    from backend.startup.background_tasks import _reset_advanced_tasks

    huerfana = await _crear_tarea(
        db_session, admin_user.id, status=TaskStatus.advanced, advanced_at=None,
    )

    _sesion_de_prueba(monkeypatch, db_session)
    await _reset_advanced_tasks()

    await db_session.refresh(huerfana)
    assert huerfana.status == TaskStatus.in_progress


@pytest.mark.asyncio
async def test_el_prefill_del_daily_incluye_las_avanzadas_de_hoy(admin_client, db_session):
    """Sin fichar tiempo: el gesto de marcar Avanzada basta para salir en el daily."""
    task = await _crear_tarea(
        db_session, admin_client.test_user.id,
        status=TaskStatus.advanced, advanced_at=date.today(),
    )

    resp = await admin_client.get("/api/dailys/prefill")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert task.title in body["text"]
    assert f"🔄 {task.title}" in body["text"]
    assert body["worked_on_count"] >= 1


@pytest.mark.asyncio
async def test_el_prefill_no_incluye_las_avanzadas_de_ayer(admin_client, db_session):
    task = await _crear_tarea(
        db_session, admin_client.test_user.id,
        status=TaskStatus.advanced, advanced_at=date.today() - timedelta(days=1),
    )

    resp = await admin_client.get("/api/dailys/prefill")
    assert resp.status_code == 200, resp.text
    assert task.title not in resp.json()["text"]


@pytest.mark.asyncio
async def test_arrancar_el_timer_devuelve_la_tarea_a_en_curso(admin_client, db_session):
    """Si sigue trabajando en ella, deja de estar "cerrada por hoy"."""
    task = await _crear_tarea(
        db_session, admin_client.test_user.id,
        status=TaskStatus.advanced, advanced_at=date.today(),
    )

    resp = await admin_client.post("/api/timer/start", json={"task_id": task.id})
    assert resp.status_code == 201, resp.text

    refreshed = await db_session.execute(select(Task).where(Task.id == task.id))
    assert refreshed.scalar_one().status == TaskStatus.in_progress
