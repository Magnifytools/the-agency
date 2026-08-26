"""Journal de cambios deshacibles (Undo de los últimos cambios).

Captura AUTOMÁTICA vía eventos de sesión de SQLAlchemy: ninguna ruta tiene que
acordarse de llamar a nada, así que no se puede olvidar un endpoint nuevo.

Una entrada de ``change_logs`` = una TRANSACCIÓN confirmada por un usuario, no
una fila. Borrar un proyecto desvincula sus tareas dentro de la misma
transacción, y lo que el usuario quiere deshacer es *eso*, de una vez. Por eso
se agrupa: la entrada lleva la lista de operaciones y el undo las revierte
todas.

Ciclo de vida
-------------
``before_flush``  snapshot de lo que va a cambiar. Para un UPDATE sólo se
                  guardan las columnas que cambian de verdad (valor viejo y
                  nuevo), leídas del historial de atributos, que en este punto
                  todavía está intacto.
``after_flush``   rellena los PK de los INSERT, que hasta aquí no existen.
``after_commit``  colapsa lo acumulado en UNA entrada y la escribe desde una
                  sesión aparte.

La escritura es best-effort y fuera del camino crítico: si falla se pierde la
entrada del journal, nunca la respuesta al usuario (mismo criterio que
UsageTrackerMiddleware).

Sólo se registra si hay ACTOR — lo pone ``get_current_user``. Los barridos
nocturnos, el seed y los scripts corren sin actor y no ensucian el historial
con cambios que nadie ha hecho a mano.

Lo que NO se captura, a propósito:
- ``UPDATE``/``DELETE`` masivos construidos con ``sqlalchemy.update()`` /
  ``delete()``: no pasan por la capa ORM y no disparan estos eventos. El purgado
  duro de clientes (``DELETE /api/clients/{id}/hard``) es de ese tipo y además
  es irreversible por diseño.
- Los módulos financieros (ver "No tocar" en CLAUDE.md).
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import enum
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, Float, Numeric, event, inspect as sa_inspect
from sqlalchemy.orm import Session

from backend.db.models import (
    Client,
    GrowthIdea,
    Lead,
    LeadActivity,
    Project,
    ProjectPhase,
    Task,
    TaskChecklist,
)

logger = logging.getLogger(__name__)

_INFO_KEY = "_change_journal_pending"

#: Tope de filas por entrada. Una importación masiva no debe generar un JSON
#: gigante ni una entrada de historial que nadie va a querer deshacer entera.
MAX_OPERATIONS = 300

#: Columnas que nunca viajan en el snapshot: las gestiona el ORM/servidor.
_SKIP_COLUMNS = {"updated_at"}


# ── Actor ────────────────────────────────────────────────────────────────────

_actor: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "change_journal_actor", default=None
)
_paused: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "change_journal_paused", default=False
)


def set_actor(user_id: Optional[int]) -> None:
    """Marca quién es el autor de los cambios de esta petición."""
    _actor.set(user_id)


def current_actor() -> Optional[int]:
    return _actor.get()


@contextlib.contextmanager
def paused():
    """Desactiva la captura dentro del bloque.

    Lo usa el propio undo: revertir un cambio no es un cambio nuevo que deshacer,
    o el historial se convertiría en un bucle deshacer/rehacer/deshacer.
    """
    token = _paused.set(True)
    try:
        yield
    finally:
        _paused.reset(token)


# ── Entidades cubiertas ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Spec:
    entity_type: str
    label_attr: str
    module: str          # módulo de permisos que hay que poder escribir
    noun: str            # cómo se llama en la UI
    feminine: bool       # para concordar "creada/creado" en el label
    rank: int            # 0 = padre, 1 = hijo (manda el orden de restauración)


#: Padres (rank 0) e hijos "propios" (rank 1). Los hijos entran porque se borran
#: en cascada con el padre: sin ellos, deshacer un borrado devolvería la tarea
#: pero se habría comido su checklist en silencio.
_SPECS: dict[type, _Spec] = {
    Task:          _Spec("task",          "title",        "tasks",    "Tarea",     True,  0),
    Project:       _Spec("project",       "name",         "projects", "Proyecto",  False, 0),
    Client:        _Spec("client",        "name",         "clients",  "Cliente",   False, 0),
    Lead:          _Spec("lead",          "company_name", "growth",   "Lead",      False, 0),
    GrowthIdea:    _Spec("growth_idea",   "title",        "growth",   "Idea",      True,  0),
    ProjectPhase:  _Spec("project_phase", "name",         "projects", "Fase",      True,  1),
    TaskChecklist: _Spec("task_checklist", "text",        "tasks",    "Subtarea",  True,  1),
    LeadActivity:  _Spec("lead_activity", "title",        "growth",   "Actividad", True,  1),
}

#: entity_type -> modelo, para que el undo sepa qué tabla tocar.
MODELS_BY_TYPE: dict[str, type] = {spec.entity_type: model for model, spec in _SPECS.items()}
SPECS_BY_TYPE: dict[str, _Spec] = {spec.entity_type: spec for spec in _SPECS.values()}


def _spec_for(obj: Any) -> Optional[_Spec]:
    return _SPECS.get(type(obj))


# ── (De)serialización ────────────────────────────────────────────────────────

def serialize(value: Any) -> Any:
    """Valor de columna -> algo que quepa en JSONB sin perder precisión.

    Los Decimal viajan como string a propósito: ``Numeric(12, 2)`` es dinero y
    pasar por float redondearía céntimos al restaurar.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def deserialize(column, value: Any) -> Any:
    """Inverso de :func:`serialize`, guiado por el tipo real de la columna."""
    if value is None:
        return None
    col_type = column.type
    if isinstance(col_type, SAEnum) and getattr(col_type, "enum_class", None) is not None:
        return col_type.enum_class(value)
    # Float hereda de Numeric: hay que descartarlo antes o los float acabarían
    # como Decimal.
    if isinstance(col_type, Numeric) and not isinstance(col_type, Float):
        return Decimal(str(value))
    if isinstance(col_type, DateTime):
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(col_type, Date):
        return date.fromisoformat(value) if isinstance(value, str) else value
    return value


def _snapshot(obj: Any) -> dict[str, Any]:
    state = sa_inspect(obj)
    out: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        if attr.key in _SKIP_COLUMNS:
            continue
        out[attr.key] = serialize(getattr(obj, attr.key, None))
    return out


def _diff(obj: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Columnas que cambian de verdad: (valores viejos, valores nuevos)."""
    state = sa_inspect(obj)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        if attr.key in _SKIP_COLUMNS:
            continue
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if old == new:
            continue
        before[attr.key] = serialize(old)
        after[attr.key] = serialize(new)
    return before, after


def _label_of(spec: _Spec, data: dict[str, Any]) -> str:
    raw = data.get(spec.label_attr)
    text = str(raw).strip() if raw not in (None, "") else "(sin título)"
    if len(text) > 80:
        text = text[:77] + "…"
    return text


# ── Acumulación durante la transacción ───────────────────────────────────────

@dataclass
class _Op:
    spec: _Spec
    action: str                      # create | update | delete
    obj: Any = None                  # sólo mientras dura la transacción
    entity_id: Optional[int] = None
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    name: str = ""


def _pending(session: Session) -> list[_Op]:
    return session.info.setdefault(_INFO_KEY, [])


@event.listens_for(Session, "before_flush")
def _capture(session: Session, flush_context, instances) -> None:
    if _actor.get() is None or _paused.get():
        return
    try:
        ops = _pending(session)
        for obj in session.new:
            spec = _spec_for(obj)
            if spec is None:
                continue
            after = _snapshot(obj)
            ops.append(_Op(spec=spec, action="create", obj=obj, after=after,
                           name=_label_of(spec, after)))
        for obj in session.dirty:
            spec = _spec_for(obj)
            if spec is None:
                continue
            before, after = _diff(obj)
            if not after:
                continue
            ops.append(_Op(spec=spec, action="update", obj=obj,
                           entity_id=getattr(obj, "id", None),
                           before=before, after=after,
                           name=_label_of(spec, _snapshot(obj))))
        for obj in session.deleted:
            spec = _spec_for(obj)
            if spec is None:
                continue
            before = _snapshot(obj)
            ops.append(_Op(spec=spec, action="delete", obj=obj,
                           entity_id=getattr(obj, "id", None),
                           before=before, name=_label_of(spec, before)))
    except Exception as exc:  # nunca romper el flush del usuario
        logger.debug("change_journal: fallo capturando cambios: %s", exc)
        session.info.pop(_INFO_KEY, None)


@event.listens_for(Session, "after_flush")
def _resolve_ids(session: Session, flush_context) -> None:
    """Los INSERT no tienen PK hasta después del flush."""
    ops = session.info.get(_INFO_KEY)
    if not ops:
        return
    for op in ops:
        if op.entity_id is None and op.obj is not None:
            op.entity_id = getattr(op.obj, "id", None)
            if op.action == "create":
                op.after["id"] = op.entity_id


@event.listens_for(Session, "after_commit")
def _dispatch(session: Session) -> None:
    ops = session.info.pop(_INFO_KEY, None)
    if not ops:
        return
    try:
        entry = build_entry(ops, actor_id=_actor.get())
    except Exception as exc:
        logger.debug("change_journal: fallo construyendo la entrada: %s", exc)
        return
    if entry is None:
        return
    _sink(entry)


def _sink(entry: dict[str, Any]) -> None:
    """Saca la entrada del camino crítico.

    Función aparte y llamada por nombre para poder sustituirla en los tests: así
    se puede comprobar QUÉ se registra sin depender de una tarea en segundo plano.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("change_journal: sin event loop, entrada descartada")
        return
    loop.create_task(_write(entry))


@event.listens_for(Session, "after_rollback")
@event.listens_for(Session, "after_soft_rollback")
def _discard(session: Session, *args) -> None:
    session.info.pop(_INFO_KEY, None)


# ── Colapso a una sola entrada ───────────────────────────────────────────────

#: Qué acción manda al titular la entrada cuando la transacción toca varias filas.
_ACTION_WEIGHT = {"delete": 0, "create": 1, "update": 2}


def _collapse(ops: list[_Op]) -> list[_Op]:
    """Una fila tocada varias veces en la misma transacción = una sola operación."""
    merged: dict[tuple[str, Optional[int]], _Op] = {}
    order: list[tuple[str, Optional[int]]] = []
    for op in ops:
        key = (op.spec.entity_type, op.entity_id)
        prev = merged.get(key)
        if prev is None:
            merged[key] = op
            order.append(key)
            continue
        if prev.action == "create" and op.action == "delete":
            # Creada y borrada en la misma transacción: no queda nada que deshacer.
            merged.pop(key)
            order.remove(key)
            continue
        if prev.action == "create":
            prev.after.update(op.after)
            prev.name = op.name or prev.name
        elif op.action == "delete":
            # El "antes" bueno es el más viejo que tengamos de cada columna.
            op.before = {**op.before, **prev.before}
            op.name = prev.name or op.name
            merged[key] = op
        else:
            prev.before = {**op.before, **prev.before}
            prev.after.update(op.after)
            prev.name = op.name or prev.name
    return [merged[k] for k in order]


def build_entry(ops: list[_Op], actor_id: Optional[int]) -> Optional[dict[str, Any]]:
    """Colapsa las operaciones de una transacción en la fila de ``change_logs``."""
    ops = [op for op in _collapse(ops) if op.entity_id is not None]
    if not ops:
        return None
    if len(ops) > MAX_OPERATIONS:
        logger.info(
            "change_journal: transacción de %d filas por encima del tope (%d), no se registra",
            len(ops), MAX_OPERATIONS,
        )
        return None

    headline = min(ops, key=lambda o: (o.spec.rank, _ACTION_WEIGHT.get(o.action, 3)))
    verb = {
        "create": "creada" if headline.spec.feminine else "creado",
        "update": "editada" if headline.spec.feminine else "editado",
        "delete": "eliminada" if headline.spec.feminine else "eliminado",
    }[headline.action]
    label = f"{headline.spec.noun} «{headline.name}» {verb}"

    return {
        "user_id": actor_id,
        "entity_type": headline.spec.entity_type,
        "entity_id": headline.entity_id,
        "action": headline.action,
        "label": label[:255],
        "operations": [
            {
                "entity_type": op.spec.entity_type,
                "entity_id": op.entity_id,
                "action": op.action,
                "rank": op.spec.rank,
                "name": op.name,
                "before": op.before or None,
                "after": op.after or None,
            }
            for op in ops
        ],
    }


async def _write(entry: dict[str, Any]) -> None:
    """Escribe la entrada en su propia sesión. Best-effort."""
    try:
        from backend.db.database import async_session
        from backend.db.models import ChangeLog

        async with async_session() as db:
            db.add(ChangeLog(**entry))
            await db.commit()
    except Exception as exc:
        logger.debug("change_journal: no se pudo escribir la entrada: %s", exc)
