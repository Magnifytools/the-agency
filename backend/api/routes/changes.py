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
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import ChangeLog, User, UserRole
from backend.services import change_journal
from backend.services.change_journal import (
    MODELS_BY_TYPE,
    SPECS_BY_TYPE,
    deserialize,
    serialize,
)

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


async def _undo_delete(db: AsyncSession, op: dict, warnings: list[str]) -> int:
    """Reinsertar la fila borrada, con su id original."""
    model = MODELS_BY_TYPE[op["entity_type"]]
    before = op.get("before") or {}
    existing = await db.get(model, op["entity_id"])
    if existing is not None:
        warnings.append(f"«{op.get('name') or op['entity_id']}» ya existía: no se ha vuelto a crear.")
        return 0
    cols = _columns(model)
    values = {k: deserialize(cols[k], v) for k, v in before.items() if k in cols}
    db.add(model(**values))
    return 1


async def _undo_create(db: AsyncSession, op: dict, warnings: list[str]) -> int:
    """Borrar lo que se había creado."""
    model = MODELS_BY_TYPE[op["entity_type"]]
    row = await db.get(model, op["entity_id"])
    if row is None:
        warnings.append(f"«{op.get('name') or op['entity_id']}» ya no existe: nada que deshacer.")
        return 0
    after = op.get("after") or {}
    changed = [k for k, v in after.items() if k != "id" and serialize(getattr(row, k, None)) != v]
    if changed:
        warnings.append(
            f"«{op.get('name') or op['entity_id']}» se había editado después ({', '.join(changed[:3])}); "
            "se ha eliminado igualmente."
        )
    await db.delete(row)
    return 1


async def _undo_update(db: AsyncSession, op: dict, warnings: list[str]) -> int:
    """Devolver las columnas a su valor anterior, respetando cambios de terceros."""
    model = MODELS_BY_TYPE[op["entity_type"]]
    row = await db.get(model, op["entity_id"])
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
        select(ChangeLog).where(ChangeLog.id == change_id)
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
    reinserts = sorted([o for o in operations if o["action"] == "delete"], key=lambda o: o.get("rank", 0))
    updates = [o for o in operations if o["action"] == "update"]
    removals = sorted([o for o in operations if o["action"] == "create"],
                      key=lambda o: o.get("rank", 0), reverse=True)

    warnings: list[str] = []
    restored = 0
    try:
        with change_journal.paused():
            for op in reinserts:
                restored += await _undo_delete(db, op, warnings)
            await db.flush()
            for op in updates:
                restored += await _undo_update(db, op, warnings)
            for op in removals:
                restored += await _undo_create(db, op, warnings)

            # func.now(): mismo reloj que created_at (el del servidor), o las dos
            # marcas de la misma fila saldrían de husos distintos.
            entry.undone_at = func.now()
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
