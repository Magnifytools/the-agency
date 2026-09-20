"""Undo — deshacer los últimos cambios del usuario.

Lee el journal que escribe ``backend/services/change_journal.py`` (una fila por
acción de usuario) y sabe aplicar la operación inversa:

    create  ->  borrar la fila
    update  ->  devolver las columnas a su valor anterior
    delete  ->  reinsertar la fila con su id original

Reglas de la casa:
- Cada usuario deshace SUS cambios. No es un historial de la agencia.
- Se comprueba el permiso de escritura del módulo EN EL MOMENTO del undo: haber
  podido hacer el cambio ayer no da derecho a tocarlo hoy.
- Si otra persona ha tocado después una columna que íbamos a restaurar, esa
  columna se deja como está y se informa. Deshacer no puede pisar en silencio
  el trabajo de otro.
- Deshacer no se registra como cambio nuevo (``change_journal.paused()``), o el
  historial se volvería un bucle.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_serializer
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import (
    ChangeLog,
    ClientContact,
    Task,
    TaskChecklist,
    TimeEntry,
    User,
    UserRole,
)
from backend.services import change_journal
from backend.services.change_journal import (
    MODELS_BY_TYPE,
    SPECS_BY_TYPE,
    deserialize,
    serialize,
)
from backend.services.temporal import utc_isoformat, utc_now_naive

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/changes", tags=["changes"])

#: Cuántos cambios se ofrecen para deshacer. Es una red de seguridad para el
#: "uy, no era eso", no un control de versiones.
UNDO_WINDOW = 5


class ChangeEntry(BaseModel):
    id: int
    label: str
    action: str
    entity_type: str
    entity_id: Optional[int]
    created_at: datetime
    operation_count: int

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return utc_isoformat(value)


class UndoResult(BaseModel):
    id: int
    label: str
    restored: int
    warnings: list[str]


def _can_write(user: User, module: str) -> bool:
    if user.role == UserRole.admin:
        return True
    try:
        perms = user.permissions
    except Exception:
        perms = []
    return any(p.module == module and p.can_write for p in perms)


def _check_permissions(user: User, operations: list[dict]) -> None:
    modules = set()
    for op in operations:
        spec = SPECS_BY_TYPE.get(op.get("entity_type", ""))
        if spec is not None:
            modules.add(spec.module)
    missing = sorted(m for m in modules if not _can_write(user, m))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso de escritura para deshacer esto: {', '.join(missing)}",
        )


@router.get("/recent", response_model=list[ChangeEntry])
async def recent_changes(
    limit: int = Query(UNDO_WINDOW, ge=1, le=UNDO_WINDOW),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Los últimos cambios del usuario que todavía se pueden deshacer."""
    rows = (await db.execute(
        select(ChangeLog)
        .where(ChangeLog.user_id == current_user.id, ChangeLog.undone_at.is_(None))
        .order_by(desc(ChangeLog.created_at), desc(ChangeLog.id))
        .limit(limit)
    )).scalars().all()

    return [
        ChangeEntry(
            id=row.id,
            label=row.label,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            created_at=row.created_at,
            operation_count=len(row.operations or []),
        )
        for row in rows
    ]


def _columns(model: type) -> dict[str, Any]:
    return {attr.key: attr.expression for attr in model.__mapper__.column_attrs}


def _order_fk_operations(operations: list[dict], *, parents_first: bool) -> list[dict]:
    """Order one journal subset by its concrete FK values.

    Static entity ranks cannot express that Project is both a child of Client
    and a parent of other work.  Build the order from the rows captured in this
    change, retaining rank/insertion order only as a deterministic fallback.
    """
    indexed = list(enumerate(operations))
    indexed.sort(key=lambda item: (item[1].get("rank", 0), item[0]))
    by_table_and_id: dict[tuple[str, int], tuple[str, int]] = {}
    for _, op in indexed:
        model = MODELS_BY_TYPE.get(op.get("entity_type"))
        entity_id = op.get("entity_id")
        if model is not None and entity_id is not None:
            by_table_and_id[(model.__table__.name, entity_id)] = (op["entity_type"], entity_id)

    parents: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for _, op in indexed:
        identity = (op.get("entity_type"), op.get("entity_id"))
        model = MODELS_BY_TYPE.get(op.get("entity_type"))
        snapshot = op.get("before") if op.get("action") == "delete" else op.get("after")
        dependencies: set[tuple[str, int]] = set()
        if model is not None:
            for column in model.__table__.columns:
                value = (snapshot or {}).get(column.key)
                if value is None:
                    continue
                for foreign_key in column.foreign_keys:
                    parent = by_table_and_id.get((foreign_key.column.table.name, value))
                    if parent is not None and parent != identity:
                        dependencies.add(parent)
        parents[identity] = dependencies

    emitted: set[tuple[str, int]] = set()
    ordered: list[dict] = []
    pending = [op for _, op in indexed]
    while pending:
        ready_index = next((
            index for index, op in enumerate(pending)
            if parents[(op.get("entity_type"), op.get("entity_id"))].issubset(emitted)
        ), None)
        # Cyclic/self-referential legacy data keeps the deterministic fallback.
        index = ready_index if ready_index is not None else 0
        op = pending.pop(index)
        ordered.append(op)
        emitted.add((op.get("entity_type"), op.get("entity_id")))
    return ordered if parents_first else list(reversed(ordered))


async def _manual_time_conflict(db: AsyncSession, operations: list[dict]) -> str | None:
    """Preflight a grouped manual-time undo so Task and TimeEntry stay atomic."""
    for op in operations:
        if op.get("entity_type") != "time_entry":
            continue
        model = MODELS_BY_TYPE["time_entry"]
        row = (await db.execute(
            select(model).where(model.id == op["entity_id"]).with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()
        action = op.get("action")
        if action == "create":
            if row is None:
                return "El registro manual ya no existe"
            after = op.get("after") or {}
            if any(
                serialize(getattr(row, k, None)) != after.get(k)
                for k in {"minutes", "task_id", "user_id", "date", "notes"}
                if k in after
            ):
                return "El registro manual cambió después"
        elif action == "update":
            if row is None:
                return "El registro manual ya no existe"
            after = op.get("after") or {}
            if any(
                serialize(getattr(row, k, None)) != expected
                for k, expected in after.items()
                if k != "id"
            ):
                return "El registro manual cambió después"
        elif action == "delete" and row is not None:
            return "El registro manual fue recreado después"
    return None


async def _lock_operation_rows(db: AsyncSession, operations: list[dict]) -> dict[tuple[str, int], Any]:
    """Lock every existing journal target in one deterministic order.

    Conflict checks and their inverse writes must observe the same version.  A
    ChangeLog lock serializes two Undo clicks, but it does not serialize an
    ordinary edit to the affected Project/Client/etc.
    """
    locked: dict[tuple[str, int], Any] = {}
    grouped: dict[str, set[int]] = {}
    for op in operations:
        entity_type, entity_id = op.get("entity_type"), op.get("entity_id")
        if entity_type in MODELS_BY_TYPE and entity_id is not None:
            grouped.setdefault(entity_type, set()).add(entity_id)
    time_ops = [op for op in operations if op.get("entity_type") == "time_entry"]
    time_ids = [op["entity_id"] for op in time_ops if op.get("entity_id") is not None]
    anticipated_task_ids = {
        task_id
        for op in time_ops
        for task_id in ((op.get("before") or {}).get("task_id"), (op.get("after") or {}).get("task_id"))
        if task_id is not None
    }
    if time_ids:
        anticipated_task_ids.update(task_id for task_id in (await db.execute(
            select(TimeEntry.task_id).where(TimeEntry.id.in_(time_ids))
        )).scalars().all() if task_id is not None)
    if anticipated_task_ids:
        grouped.setdefault("task", set()).update(anticipated_task_ids)
    checklist_ops = [op for op in operations if op.get("entity_type") == "task_checklist"]
    checklist_ids = [op["entity_id"] for op in checklist_ops if op.get("entity_id") is not None]
    checklist_task_ids = {
        task_id for op in checklist_ops
        for task_id in ((op.get("before") or {}).get("task_id"), (op.get("after") or {}).get("task_id"))
        if task_id is not None
    }
    if checklist_ids:
        checklist_task_ids.update((await db.scalars(
            select(TaskChecklist.task_id).where(TaskChecklist.id.in_(checklist_ids))
        )).all())
    if checklist_task_ids:
        grouped.setdefault("task", set()).update(checklist_task_ids)
    contact_ops = [op for op in operations if op.get("entity_type") == "client_contact"]
    contact_ids = [op["entity_id"] for op in contact_ops if op.get("entity_id") is not None]
    anticipated_client_ids = {
        client_id for op in contact_ops
        for client_id in ((op.get("before") or {}).get("client_id"), (op.get("after") or {}).get("client_id"))
        if client_id is not None
    }
    if contact_ids:
        anticipated_client_ids.update((await db.scalars(
            select(ClientContact.client_id).where(ClientContact.id.in_(contact_ids))
        )).all())
    if anticipated_client_ids:
        grouped.setdefault("client", set()).update(anticipated_client_ids)
    # Undo can restore an old dependency, reopen a completed dependent, or
    # reinsert a deleted task. Lock both current and intended parents in the
    # same deterministic task order before inspecting their lifecycle.
    dependency_ids = {
        dependency_id for op in operations if op.get("entity_type") == "task"
        for dependency_id in ((op.get("before") or {}).get("depends_on"), (op.get("after") or {}).get("depends_on"))
        if dependency_id is not None
    }
    if grouped.get("task"):
        dependency_ids.update(dependency_id for dependency_id in (await db.scalars(
            select(Task.depends_on).where(Task.id.in_(sorted(grouped["task"])))
        )).all() if dependency_id is not None)
    if dependency_ids:
        grouped.setdefault("task", set()).update(dependency_ids)
    # Alphabetical order is stable and keeps task before time_entry, matching
    # the time writer's lock protocol.
    for entity_type in sorted(grouped):
        model = MODELS_BY_TYPE[entity_type]
        rows = (await db.execute(
            select(model).where(model.id.in_(sorted(grouped[entity_type])))
            .order_by(model.id).options(noload("*")).with_for_update()
            .execution_options(populate_existing=True)
        )).scalars().all()
        locked.update({(entity_type, row.id): row for row in rows})
    # A TimeEntry may have moved after the preliminary scalar read. Tasks are
    # already locked at this point; never continue with an unprotected task.
    for op in time_ops:
        row = locked.get(("time_entry", op.get("entity_id")))
        if row is not None and row.task_id is not None and row.task_id not in anticipated_task_ids:
            raise HTTPException(409, "El registro de tiempo cambió de tarea; vuelve a intentarlo")
    for op in checklist_ops:
        row = locked.get(("task_checklist", op.get("entity_id")))
        if row is not None and row.task_id not in checklist_task_ids:
            raise HTTPException(409, "La subtarea cambió de tarea; vuelve a intentarlo")
    for op in contact_ops:
        row = locked.get(("client_contact", op.get("entity_id")))
        if row is not None and row.client_id not in anticipated_client_ids:
            raise HTTPException(409, "El contacto cambió de cliente; vuelve a intentarlo")
    return locked


async def _preflight_contact_primaries(
    db: AsyncSession, operations: list[dict], locked: dict[tuple[str, int], Any],
) -> None:
    """Reject an Undo whose final state would create two primary contacts."""
    contact_ops = [op for op in operations if op.get("entity_type") == "client_contact"]
    if not contact_ops:
        return
    client_ids = {
        client_id for op in contact_ops
        for client_id in ((op.get("before") or {}).get("client_id"), (op.get("after") or {}).get("client_id"))
        if client_id is not None
    }
    client_ids.update(
        row.client_id for op in contact_ops
        if (row := locked.get(("client_contact", op.get("entity_id")))) is not None
    )
    primary_rows = (await db.execute(
        select(ClientContact.id, ClientContact.client_id)
        .where(
            ClientContact.client_id.in_(sorted(client_ids)),
            ClientContact.is_primary.is_(True),
        )
        .order_by(ClientContact.client_id, ClientContact.id)
    )).all()
    primaries = {client_id: set() for client_id in client_ids}
    for contact_id, client_id in primary_rows:
        primaries[client_id].add(contact_id)

    for op in contact_ops:
        contact_id, action = op.get("entity_id"), op.get("action")
        before, after = op.get("before") or {}, op.get("after") or {}
        row = locked.get(("client_contact", contact_id))
        current_client_id = row.client_id if row is not None else None
        if action == "create":
            if current_client_id is not None:
                primaries[current_client_id].discard(contact_id)
        elif action == "delete" and row is None and before.get("is_primary"):
            primaries[before["client_id"]].add(contact_id)
        elif action == "update" and row is not None and "is_primary" in before:
            if "is_primary" not in after or serialize(row.is_primary) == after["is_primary"]:
                primaries[row.client_id].discard(contact_id)
                if before["is_primary"]:
                    primaries[row.client_id].add(contact_id)

    if any(len(contact_ids) > 1 for contact_ids in primaries.values()):
        raise HTTPException(
            status_code=409,
            detail="Ya existe otro contacto principal; no se ha deshecho el cambio",
        )


async def _preflight_retirement(
    db: AsyncSession, operations: list[dict], locked: dict[tuple[str, int], Any],
) -> None:
    """An old Undo must respect today's withdrawal and its dependent work."""
    from backend.services.task_retirement import ensure_can_restore, ensure_can_retire

    pair = {"retired_at", "retired_reason"}
    annotations = {"title", "description", "link_url"}
    manual_task_ids = {
        task_id for op in operations if op.get("entity_type") == "time_entry"
        for task_id in ((op.get("before") or {}).get("task_id"), (op.get("after") or {}).get("task_id"))
        if task_id is not None
    }
    for op in operations:
        entity_type, action = op.get("entity_type"), op.get("action")
        row = locked.get((entity_type, op.get("entity_id")))
        before, after = op.get("before") or {}, op.get("after") or {}
        if entity_type == "task_checklist":
            task_id = row.task_id if row is not None else before.get("task_id")
            task = locked.get(("task", task_id))
            if task is not None and task.retired_at is not None:
                raise HTTPException(409, "Restaura la tarea antes de deshacer cambios de su checklist")
        if entity_type != "task" or row is None:
            continue
        if action == "create" and row.retired_at is not None:
            raise HTTPException(409, "La tarea fue retirada después; no se ha eliminado")
        if action != "update":
            continue
        if pair.intersection(before):
            # The pair is one domain decision, never a partially restored patch.
            if not pair.issubset(before) or not pair.issubset(after) or any(
                serialize(getattr(row, key)) != after[key] for key in pair
            ):
                raise HTTPException(409, "La retirada cambió después; no se ha deshecho")
            if before["retired_at"] is None:
                await ensure_can_restore(db, row)
            else:
                await ensure_can_retire(db, row)
        elif row.retired_at is not None:
            allowed = annotations | ({"actual_minutes"} if row.id in manual_task_ids else set())
            if set(before) - allowed:
                raise HTTPException(409, "Restaura la tarea antes de deshacer cambios de su trabajo")

    # Validate the actual inverse result, including partial conflict-preserving
    # updates. Checking only retired_* would miss Undo of completed/status,
    # dependency edits and deletion of a formerly active dependent.
    resulting: dict[int, dict | None] = {}
    for op in operations:
        if op.get("entity_type") != "task":
            continue
        task_id, action = op["entity_id"], op.get("action")
        row = locked.get(("task", task_id))
        before, after = op.get("before") or {}, op.get("after") or {}
        state = {key: serialize(getattr(row, key)) for key in ("status", "retired_at", "depends_on")} if row is not None else None
        if action == "delete" and row is None:
            state = {key: before.get(key) for key in ("status", "retired_at", "depends_on")}
        elif action == "create":
            state = None
        elif action == "update" and state is not None:
            for key in state:
                if key in before and (key not in after or state[key] == after[key]):
                    state[key] = before[key]
        resulting[task_id] = state
    for state in resulting.values():
        if state is None or state["retired_at"] is not None or state["status"] == "completed":
            continue
        dependency_id = state["depends_on"]
        if dependency_id is None:
            continue
        if dependency_id in resulting:
            parent = resulting[dependency_id]
            valid = parent is not None and parent["retired_at"] is None
        else:
            parent = locked.get(("task", dependency_id))
            valid = parent is not None and parent.retired_at is None
        if not valid:
            raise HTTPException(409, "La dependencia fue retirada o cambió; revísala antes de deshacer")


def _created_children(operations: list[dict]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for op in operations:
        if op.get("action") == "create" and op.get("entity_id") is not None:
            model = MODELS_BY_TYPE.get(op.get("entity_type"))
            if model is not None:
                out.setdefault(model.__table__.name, set()).add(op["entity_id"])
    return out


async def _unexpected_dependents(db: AsyncSession, model: type, entity_ids: set[int],
                                 allowed_created: dict[str, set[int]]) -> dict[int, list[str]]:
    """Return referencing rows that this Undo did not create and must preserve."""
    conflicts: dict[int, list[str]] = {entity_id: [] for entity_id in entity_ids}
    target_table = model.__table__
    # Metadata includes non-journal children too (comments, attachments,
    # evidence...). Those are precisely the rows a parent-only snapshot misses.
    for table in sorted(target_table.metadata.tables.values(), key=lambda item: item.name):
        pk_columns = list(table.primary_key.columns)
        for column in table.columns:
            if not any(fk.column.table is target_table for fk in column.foreign_keys):
                continue
            if len(pk_columns) == 1:
                rows = (await db.execute(
                    select(column, pk_columns[0]).where(column.in_(sorted(entity_ids)))
                )).all()
            else:
                # Composite identities cannot be matched to journal child IDs;
                # conservatively treat every reference as later work.
                rows = (await db.execute(
                    select(column, func.count()).where(column.in_(sorted(entity_ids))).group_by(column)
                )).all()
            by_parent: dict[int, int] = {}
            for parent_id, child_id in rows:
                if len(pk_columns) != 1:
                    by_parent[parent_id] = int(child_id)
                elif child_id not in allowed_created.get(table.name, set()):
                    by_parent[parent_id] = by_parent.get(parent_id, 0) + 1
            for parent_id, child_count in by_parent.items():
                conflicts[parent_id].append(f"{table.name} ({child_count})")
    return conflicts


async def _preflight_create_removals(db: AsyncSession, removals: list[dict],
                                     locked: dict[tuple[str, int], Any],
                                     operations: list[dict]) -> None:
    """Refuse the whole Undo before it can delete later work."""
    allowed_created = _created_children(operations)
    by_type: dict[str, list[dict]] = {}
    for op in removals:
        row = locked.get((op["entity_type"], op["entity_id"]))
        if row is None:
            continue
        by_type.setdefault(op["entity_type"], []).append(op)
        after = op.get("after") or {}
        columns = _columns(type(row))
        changed = []
        for key, value in after.items():
            if key == "id" or key not in columns or serialize(getattr(row, key, None)) == value:
                continue
            column = columns[key]
            # Legacy INSERT snapshots were taken before SQLAlchemy applied
            # defaults. Only accept an exact static default; new snapshots store
            # the actual post-flush value and therefore never need this fallback.
            if value is None:
                if key == "created_at":
                    continue  # immutable legacy INSERT timestamp
                default = column.default
                if default is not None and default.is_scalar and serialize(default.arg) == serialize(getattr(row, key, None)):
                    continue
            changed.append(key)
        if changed:
            raise HTTPException(
                status_code=409,
                detail=(f"«{op.get('name') or op['entity_id']}» cambió después "
                        f"({', '.join(changed[:3])}); no se ha eliminado."),
            )
    for entity_type in sorted(by_type):
        dependent_map = await _unexpected_dependents(
            db, MODELS_BY_TYPE[entity_type], {op["entity_id"] for op in by_type[entity_type]}, allowed_created,
        )
        for op in by_type[entity_type]:
            dependents = dependent_map[op["entity_id"]]
            if dependents:
                logger.info(
                    "Undo rechazado para %s %s por dependencias posteriores: %s",
                    entity_type, op["entity_id"], ", ".join(dependents),
                )
                raise HTTPException(
                    status_code=409,
                    detail=(f"«{op.get('name') or op['entity_id']}» tiene trabajo añadido después; "
                            "no se ha eliminado."),
                )


async def _undo_delete(db: AsyncSession, op: dict, warnings: list[str], row: Any = None) -> int:
    """Reinsertar la fila borrada, con su id original."""
    model = MODELS_BY_TYPE[op["entity_type"]]
    before = op.get("before") or {}
    existing = row
    if existing is not None:
        warnings.append(f"«{op.get('name') or op['entity_id']}» ya existía: no se ha vuelto a crear.")
        return 0
    cols = _columns(model)
    values = {k: deserialize(cols[k], v) for k, v in before.items() if k in cols}
    db.add(model(**values))
    return 1


async def _relink_restored_recurrence_receipts(
    db: AsyncSession, reinserts: list[dict],
) -> None:
    """Restore receipt provenance only from an explicit occurrence identity."""
    from backend.db.models import TaskRecurrenceOccurrence

    task_ops = [op for op in reinserts if op.get("entity_type") == "task"]
    identities = []
    for op in task_ops:
        before = op.get("before") or {}
        parent_id = before.get("recurring_parent_id")
        occurrence_date = before.get("recurrence_occurrence_date")
        if parent_id is not None and occurrence_date is not None:
            occurrence_date = deserialize(
                _columns(Task)["recurrence_occurrence_date"], occurrence_date,
            )
            identities.append((parent_id, occurrence_date, op["entity_id"]))
    for parent_id, occurrence_date, task_id in sorted(identities):
        receipt = (await db.execute(
            select(TaskRecurrenceOccurrence)
            .where(
                TaskRecurrenceOccurrence.template_id == parent_id,
                TaskRecurrenceOccurrence.date == occurrence_date,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if receipt is None:
            continue
        if receipt.task_id is None:
            receipt.task_id = task_id
        elif receipt.task_id != task_id:
            raise HTTPException(
                status_code=409,
                detail=("La ocurrencia restaurada ya está vinculada a otra tarea; "
                        "el cambio no se ha marcado como deshecho."),
            )


async def _undo_create(db: AsyncSession, op: dict, warnings: list[str], row: Any = None) -> int:
    """Borrar lo que se había creado."""
    if row is None:
        warnings.append(f"«{op.get('name') or op['entity_id']}» ya no existe: nada que deshacer.")
        return 0
    await db.delete(row)
    return 1


async def _undo_update(db: AsyncSession, op: dict, warnings: list[str], row: Any = None) -> int:
    """Devolver las columnas a su valor anterior, respetando cambios de terceros."""
    model = MODELS_BY_TYPE[op["entity_type"]]
    if row is None:
        warnings.append(f"«{op.get('name') or op['entity_id']}» ya no existe: no se ha restaurado.")
        return 0
    before = op.get("before") or {}
    after = op.get("after") or {}
    cols = _columns(model)
    applied = 0
    skipped: list[str] = []
    for key, old_value in before.items():
        if key not in cols or key == "id":
            continue
        # Si el valor actual ya no es el que dejamos, alguien lo tocó después.
        if key in after and serialize(getattr(row, key, None)) != after[key]:
            skipped.append(key)
            continue
        setattr(row, key, deserialize(cols[key], old_value))
        applied += 1
    if skipped:
        warnings.append(
            f"«{op.get('name') or op['entity_id']}»: {', '.join(skipped)} cambió después y se ha dejado como está."
        )
    return 1 if applied else 0


@router.post("/{change_id}/undo", response_model=UndoResult)
async def undo_change(
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = (await db.execute(
        select(ChangeLog).where(ChangeLog.id == change_id).with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Ese cambio no existe")
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sólo puedes deshacer tus propios cambios")
    if entry.undone_at is not None:
        raise HTTPException(status_code=409, detail="Ese cambio ya se deshizo")

    operations = list(entry.operations or [])
    unknown = {op.get("entity_type") for op in operations} - set(MODELS_BY_TYPE)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Entidades no soportadas: {', '.join(sorted(unknown))}")
    _check_permissions(current_user, operations)

    # Orden importa: primero repongo lo borrado (padres antes que hijos) para que
    # los updates tengan a dónde apuntar, y dejo los borrados para el final
    # (hijos antes que padres) para no chocar con las claves ajenas.
    reinserts = _order_fk_operations(
        [o for o in operations if o["action"] == "delete"], parents_first=True,
    )
    updates = [o for o in operations if o["action"] == "update"]
    removals = _order_fk_operations(
        [o for o in operations if o["action"] == "create"], parents_first=False,
    )

    warnings: list[str] = []
    restored = 0
    try:
        with change_journal.paused():
            locked_rows = await _lock_operation_rows(db, operations)
            await _preflight_contact_primaries(db, operations, locked_rows)
            await _preflight_retirement(db, operations, locked_rows)
            await _preflight_create_removals(db, removals, locked_rows, operations)
            manual_ops = [op for op in operations if op.get("entity_type") == "time_entry"]
            manual_ids = [op["entity_id"] for op in manual_ops if op.get("entity_id") is not None]
            current_manual_tasks = {
                task_id for task_id in (await db.execute(
                    select(TimeEntry.task_id).where(TimeEntry.id.in_(manual_ids))
                )).scalars().all() if task_id is not None
            } if manual_ids else set()
            task_ids = {
                task_id
                for op in manual_ops
                for task_id in [
                    (op.get("after") or {}).get("task_id"),
                    (op.get("before") or {}).get("task_id"),
                ]
                if task_id is not None
            } | current_manual_tasks | {
                op["entity_id"] for op in operations
                if op.get("entity_type") == "task" and op.get("entity_id") is not None
            }
            locked_tasks = {
                task.id: task
                for task in (await db.execute(
                    select(Task).where(Task.id.in_(sorted(task_ids))).order_by(Task.id).with_for_update().execution_options(populate_existing=True)
                )).scalars().all()
            } if task_ids else {}
            if manual_ids:
                locked_manual_tasks = {
                    task_id for task_id in (await db.execute(
                        select(TimeEntry.task_id)
                        .where(TimeEntry.id.in_(manual_ids))
                        .order_by(TimeEntry.id)
                        .with_for_update().execution_options(populate_existing=True)
                    )).scalars().all() if task_id is not None
                }
                if not locked_manual_tasks.issubset(task_ids):
                    await db.rollback()
                    raise HTTPException(
                        status_code=409,
                        detail="El registro manual cambió de tarea; vuelve a intentarlo.",
                    )
            conflict = await _manual_time_conflict(db, operations)
            if conflict:
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=f"{conflict}; el ajuste no se ha marcado como deshecho.",
                )
            for op in reinserts:
                restored += await _undo_delete(
                    db, op, warnings, locked_rows.get((op["entity_type"], op["entity_id"])),
                )
            await db.flush()
            await _relink_restored_recurrence_receipts(db, reinserts)
            for op in updates:
                restored += await _undo_update(
                    db, op, warnings, locked_rows.get((op["entity_type"], op["entity_id"])),
                )
            for op in removals:
                restored += await _undo_create(
                    db, op, warnings, locked_rows.get((op["entity_type"], op["entity_id"])),
                )
            await db.flush()
            if manual_ops:
                from backend.api.routes.time_entries import _sync_task_actual_minutes
                for task_id in sorted(task_ids):
                    task = locked_tasks.get(task_id)
                    if task is not None:
                        await _sync_task_actual_minutes(db, task_id, task=task)

            entry.undone_at = utc_now_naive()
            entry.undone_by = current_user.id
            await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("Undo %d falló por integridad: %s", change_id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede deshacer: algo de lo que dependía este cambio ya no existe.",
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Undo %d falló: %s", change_id, exc)
        raise HTTPException(status_code=500, detail="No se ha podido deshacer el cambio")

    if restored == 0:
        warnings.append("No quedaba nada que restaurar.")

    return UndoResult(id=entry.id, label=entry.label, restored=restored, warnings=warnings)
