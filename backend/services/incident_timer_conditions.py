"""Cronómetro olvidado: aviso a quien lo tiene en marcha demasiadas horas.

Al pararlo, el tiempo se recorta a ``TIMER_CAP_MINUTES`` (8 h). Antes eso
pasaba en silencio y un contador olvidado dejaba días de 8 h inventadas; ahora
avisa a las ``TIMER_WARNING_MINUTES`` (4 h) y pasa a crítico al llegar al
recorte. Se resuelve solo al pararlo, y al pararlo se puede corregir.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, exists, false, func, select

from backend.core.modules import is_enabled
from backend.db.models import Notification, Task, TimeEntry
from backend.services.incident_conditions import Condition, module_permission

TIMER_RUNNING_LONG = "timer_running_long"
TIMER_CONDITIONS = (TIMER_RUNNING_LONG,)
TIMER_WARNING_MINUTES = 4 * 60
TIMER_CAP_MINUTES = 8 * 60


def elapsed_minutes(entry, now: datetime) -> int:
    """Minutos contados: lo acumulado y, si no está en pausa, lo que lleva."""
    seconds = entry.accumulated_seconds or 0
    if entry.paused_at is None and entry.started_at is not None:
        seconds += max(0, (now - entry.started_at.replace(tzinfo=None)).total_seconds())
    return int(seconds // 60)


def _key(entry_id: int) -> str:
    return f"{TIMER_RUNNING_LONG}:time_entry:{entry_id}:open"


def _hours(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min" if rest else f"{hours} h"


async def collect_timer_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    if not is_enabled("timesheet"):
        return {}
    rows = (await db.execute(select(
        TimeEntry.id, TimeEntry.started_at, TimeEntry.paused_at, TimeEntry.accumulated_seconds,
        Task.title.label("task_title"),
    ).outerjoin(Task, Task.id == TimeEntry.task_id).where(
        TimeEntry.user_id == user_id, TimeEntry.minutes.is_(None),
        module_permission(user_id, "timesheet"),
    ).order_by(TimeEntry.id))).all()
    result: dict[str, Condition] = {}
    for row in rows:
        minutes = elapsed_minutes(row, now)
        if minutes < TIMER_WARNING_MINUTES:
            continue
        capped = minutes >= TIMER_CAP_MINUTES
        level = "critical" if capped else "warning"
        key = _key(row.id)
        on = f" en «{row.task_title}»" if row.task_title else ""
        message = (
            f"Lleva {_hours(minutes)}{on}. Si se te quedó encendido, páralo y corrige el tiempo: "
            + ("al pararlo se guardan como mucho 8 h." if capped else "a las 8 h se recorta.")
        )
        result[key] = Condition(
            key=key,
            kind=TIMER_RUNNING_LONG,
            entity_id=row.id,
            title=f"Cronómetro en marcha desde hace {_hours(minutes)}"[:255],
            message=message,
            # El nivel va en la huella: al pasar a crítico vuelve a avisar.
            fingerprint=hashlib.sha256(f"{key}:{level}".encode()).hexdigest(),
            severity=level,
            entity_type="time_entry",
            entity_key=str(row.id),
            href="/tasks",
        )
    return result


def timer_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled("timesheet"):
        return false()
    source = [
        TimeEntry.id == Notification.entity_id, TimeEntry.user_id == user_id,
        TimeEntry.minutes.is_(None),
    ]
    if current_only:
        source.append(Notification.dedupe_key == func.concat(TIMER_RUNNING_LONG, ":time_entry:", TimeEntry.id, ":open"))
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "time_entry",
        Notification.type.in_(TIMER_CONDITIONS),
        module_permission(user_id, "timesheet"),
        exists().where(*source),
    )
