"""Lógica pura del journal de Undo: colapso de operaciones y (de)serialización.

Lo que se prueba aquí no toca la base de datos. La captura por eventos ORM y el
undo real viven en tests/integration/test_undo_integration.py, contra Postgres.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.db.models import Client, ClientStatus, Project, Task, TaskChecklist, TaskStatus
from backend.services import change_journal as cj


def _op(model, action, entity_id, before=None, after=None, name="X"):
    return cj._Op(
        spec=cj._SPECS[model],
        action=action,
        entity_id=entity_id,
        before=before or {},
        after=after or {},
        name=name,
    )


# ── Serialización ────────────────────────────────────────────────────────────

def test_decimal_survives_el_viaje_sin_perder_centimos():
    """Numeric(12,2) es dinero: pasar por float redondearía al restaurar."""
    value = Decimal("1234.57")
    serialized = cj.serialize(value)
    assert serialized == "1234.57"
    column = Project.__mapper__.column_attrs["monthly_fee"].expression
    assert cj.deserialize(column, serialized) == value


def test_float_no_se_convierte_en_decimal():
    """Float hereda de Numeric en SQLAlchemy; el orden de los isinstance importa."""
    column = Client.__mapper__.column_attrs["aov"].expression
    assert cj.deserialize(column, 41.5) == 41.5
    assert isinstance(cj.deserialize(column, 41.5), float)


def test_enums_van_y_vuelven_como_miembros_del_enum():
    assert cj.serialize(TaskStatus.in_progress) == "in_progress"
    column = Task.__mapper__.column_attrs["status"].expression
    assert cj.deserialize(column, "in_progress") is TaskStatus.in_progress


def test_fechas_y_timestamps_se_reconstruyen_con_su_tipo():
    dt_col = Task.__mapper__.column_attrs["due_date"].expression
    d_col = Task.__mapper__.column_attrs["scheduled_date"].expression
    assert cj.deserialize(dt_col, cj.serialize(datetime(2026, 8, 27, 9, 30))) == datetime(2026, 8, 27, 9, 30)
    assert cj.deserialize(d_col, cj.serialize(date(2026, 8, 27))) == date(2026, 8, 27)


def test_none_se_queda_en_none():
    column = Task.__mapper__.column_attrs["due_date"].expression
    assert cj.deserialize(column, None) is None


# ── Colapso: una fila tocada varias veces = una sola operación ───────────────

def test_dos_updates_seguidos_conservan_el_valor_mas_viejo():
    ops = [
        _op(Task, "update", 1, before={"title": "A"}, after={"title": "B"}),
        _op(Task, "update", 1, before={"title": "B"}, after={"title": "C"}),
    ]
    collapsed = cj._collapse(ops)
    assert len(collapsed) == 1
    assert collapsed[0].before == {"title": "A"}
    assert collapsed[0].after == {"title": "C"}


def test_crear_y_borrar_en_la_misma_transaccion_no_deja_nada_que_deshacer():
    ops = [
        _op(Task, "create", 1, after={"id": 1, "title": "A"}),
        _op(Task, "delete", 1, before={"id": 1, "title": "A"}),
    ]
    assert cj._collapse(ops) == []


def test_update_seguido_de_delete_guarda_el_valor_original():
    """Si se edita y luego se borra, reinsertar debe devolver el título de antes."""
    ops = [
        _op(Task, "update", 1, before={"title": "Original"}, after={"title": "Editado"}),
        _op(Task, "delete", 1, before={"id": 1, "title": "Editado"}),
    ]
    collapsed = cj._collapse(ops)
    assert len(collapsed) == 1
    assert collapsed[0].action == "delete"
    assert collapsed[0].before["title"] == "Original"


def test_create_seguido_de_update_sigue_siendo_un_create():
    ops = [
        _op(Task, "create", 1, after={"id": 1, "title": "A"}),
        _op(Task, "update", 1, before={"title": "A"}, after={"title": "B"}),
    ]
    collapsed = cj._collapse(ops)
    assert len(collapsed) == 1
    assert collapsed[0].action == "create"
    assert collapsed[0].after["title"] == "B"


# ── Titular de la entrada ───────────────────────────────────────────────────

def test_el_titular_es_el_padre_aunque_llegue_despues_que_los_hijos():
    """Borrar un proyecto arrastra sus fases; el historial debe hablar del proyecto."""
    ops = [
        _op(Project, "delete", 7, before={"id": 7, "name": "Rediseño"}, name="Rediseño"),
        _op(Task, "update", 3, before={"project_id": 7}, after={"project_id": None}, name="Tarea suelta"),
    ]
    entry = cj.build_entry(ops, actor_id=1)
    assert entry["entity_type"] == "project"
    assert entry["entity_id"] == 7
    assert entry["label"] == "Proyecto «Rediseño» eliminado"
    assert len(entry["operations"]) == 2


def test_el_label_concuerda_en_genero():
    femenino = cj.build_entry([_op(Task, "create", 1, after={"id": 1}, name="Revisar sitemap")], actor_id=1)
    masculino = cj.build_entry([_op(Client, "create", 1, after={"id": 1}, name="Acme")], actor_id=1)
    assert femenino["label"] == "Tarea «Revisar sitemap» creada"
    assert masculino["label"] == "Cliente «Acme» creado"


def test_operaciones_sin_id_no_llegan_al_journal():
    """Sin PK no hay nada que deshacer: mejor no registrar que registrar basura."""
    assert cj.build_entry([_op(Task, "create", None, after={"title": "A"})], actor_id=1) is None


def test_una_transaccion_gigante_no_se_registra():
    ops = [_op(Task, "update", i, before={"status": "pending"}, after={"status": "completed"})
           for i in range(cj.MAX_OPERATIONS + 1)]
    assert cj.build_entry(ops, actor_id=1) is None


def test_el_titulo_largo_se_recorta():
    entry = cj.build_entry([_op(Task, "create", 1, after={"id": 1}, name="x" * 300)], actor_id=1)
    assert len(entry["label"]) <= 255


# ── Contrato del alcance ────────────────────────────────────────────────────

def test_solo_se_vigilan_las_entidades_operativas():
    """Finanzas queda fuera a propósito (ver "No tocar" en CLAUDE.md)."""
    assert set(cj.MODELS_BY_TYPE) == {
        "task", "project", "client", "lead", "growth_idea",
        "project_phase", "task_checklist", "lead_activity",
    }
    from backend.db.models import Expense, Income
    assert Income not in cj._SPECS and Expense not in cj._SPECS


def test_los_hijos_se_restauran_despues_que_los_padres():
    """El rank es lo que impide reinsertar una subtarea antes que su tarea."""
    assert cj._SPECS[Task].rank < cj._SPECS[TaskChecklist].rank


def test_paused_desactiva_la_captura():
    assert cj._paused.get() is False
    with cj.paused():
        assert cj._paused.get() is True
    assert cj._paused.get() is False
