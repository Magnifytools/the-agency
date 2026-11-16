"""Periodos de resumen saltados (sugerencia de Nacho, 16 nov 2026).

Un cliente con la cadencia encendida a veces no tiene resumen ese periodo:
vacaciones, el trabajo se paró, ya no se hace. Saltarlo lo da por resuelto en
todo lo que hoy decide "pendiente" o "sin entregar":

* ``report_pending`` y ``report_unsent`` (``incident_report_conditions``), y con
  ``report_unsent`` la cifra de la fila Operación;
* la señal de resúmenes del estado del cliente (``client_status._digests``);
* "Para entregar" (``report_policy.preview_items``), que lo enseña como saltado.

No entrega trabajo: "listo para entregar" no lo mira. "Volver a pendiente"
borra la fila. Mismas reglas que tocar un resumen (``authorize_digest``):
escritura de ``digests`` y ser admin o el responsable actual del cliente.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import exists, select

from backend.db.models import Client, DigestPeriodSkip, User, UserRole
from backend.services.digest_access import (
    is_current_responsible,
    user_has_digest_permission,
)
from backend.services.digest_periods import period_cadence
from backend.services.temporal import business_today

MAX_REASON = 300


def skipped_clause(client_id, period_start, period_end):
    """SQL: ese periodo del cliente está saltado (va con ``delivery_confirmed_clause``
    en ``period_settled_clause``)."""
    return exists().where(
        DigestPeriodSkip.client_id == client_id,
        DigestPeriodSkip.period_start == period_start,
        DigestPeriodSkip.period_end == period_end,
    )


async def _authorize(db, actor: User, client_id: int) -> None:
    if actor is None or not actor.is_active or not await user_has_digest_permission(db, actor.id, write=True):
        raise HTTPException(403, "Sin permiso para los resúmenes de este cliente")
    if actor.role != UserRole.admin and not await is_current_responsible(db, client_id=client_id, actor_id=actor.id):
        raise HTTPException(403, "Sólo un admin o el responsable de este cliente puede saltar un periodo")


async def skip_period(db, actor: User, *, client_id: int, period_start: date, period_end: date,
                      reason: str, today: date | None = None) -> DigestPeriodSkip:
    """Salta un periodo cerrado sin entrega confirmada. Idempotente: si ya estaba
    saltado, devuelve la fila que hay (con su motivo)."""
    # Import tardío: incident_report_conditions importa este módulo.
    from backend.services.incident_report_conditions import delivery_confirmed_clause

    reason = (reason or "").strip()
    if not reason or len(reason) > MAX_REASON:
        raise HTTPException(422, detail={"code": "invalid_reason",
                                         "message": f"Di por qué se salta (1–{MAX_REASON} caracteres)."})
    if period_cadence(period_start, period_end) is None:
        raise HTTPException(422, detail={"code": "invalid_period",
                                         "message": "El periodo tiene que ser una semana de lunes a domingo o un mes natural."})
    if period_end >= (today or business_today()):
        raise HTTPException(422, detail={"code": "open_period",
                                         "message": "Sólo se puede saltar un periodo ya cerrado."})
    if await db.get(Client, client_id) is None:
        raise HTTPException(404, "Cliente no encontrado")
    await _authorize(db, actor, client_id)

    existing = (await db.execute(select(DigestPeriodSkip).where(
        DigestPeriodSkip.client_id == client_id,
        DigestPeriodSkip.period_start == period_start,
        DigestPeriodSkip.period_end == period_end,
    ))).scalar_one_or_none()
    if existing is not None:
        return existing
    # Con entrega confirmada (o el informe SEO local entregado) no hay nada que saltar.
    if await db.scalar(select(delivery_confirmed_clause(client_id, period_start, period_end))):
        raise HTTPException(409, detail={"code": "already_delivered",
                                         "message": "Ese periodo ya tiene una entrega confirmada."})
    row = DigestPeriodSkip(client_id=client_id, period_start=period_start, period_end=period_end,
                           reason=reason, skipped_by=actor.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def unskip_period(db, actor: User, skip_id: int) -> None:
    """Vuelve a pendiente. Un salto que ya no existe es el mismo 404."""
    row = await db.get(DigestPeriodSkip, skip_id)
    if row is None:
        raise HTTPException(404, "Periodo saltado no encontrado")
    await _authorize(db, actor, row.client_id)
    await db.delete(row)
    await db.commit()


async def skips_for(db, keys: list[tuple[int, date, date]]) -> dict[tuple[int, date, date], tuple[DigestPeriodSkip, str | None]]:
    """(cliente, inicio, fin) → (salto, nombre de quien lo saltó), en una lectura."""
    if not keys:
        return {}
    client_ids = sorted({key[0] for key in keys})
    starts = sorted({key[1] for key in keys})
    rows = (await db.execute(
        select(DigestPeriodSkip, User.full_name)
        .outerjoin(User, User.id == DigestPeriodSkip.skipped_by)
        .where(DigestPeriodSkip.client_id.in_(client_ids), DigestPeriodSkip.period_start.in_(starts))
    )).all()
    wanted = set(keys)
    return {
        (skip.client_id, skip.period_start, skip.period_end): (skip, name)
        for skip, name in rows
        if (skip.client_id, skip.period_start, skip.period_end) in wanted
    }

