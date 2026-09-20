"""State invariants shared by interactive and automated task mutations."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.temporal import business_today, utc_now_naive
from backend.db.models import Task, TaskStatus, User


def _status_value(value: TaskStatus | str | None) -> str | None:
    return value.value if isinstance(value, TaskStatus) else value


async def validate_task_waiting(
    db: AsyncSession, data: dict, existing: Task | None = None, *,
    allow_past_date: bool = False,
) -> None:
    """Normalize and validate an intentional change to a task's wait state.

    Historical waiting rows can be incomplete, so unrelated edits deliberately
    bypass these checks. Leaving waiting always clears its associated fields.
    Undo may set ``allow_past_date`` to restore an explicit historical date;
    the reason, date presence and active internal owner remain mandatory.
    """
    current_status = _status_value(existing.status) if existing is not None else None
    resulting_status = _status_value(data.get("status", current_status))

    if (
        existing is not None
        and current_status == TaskStatus.waiting.value
        and "status" in data
        and resulting_status != TaskStatus.waiting.value
    ):
        data["waiting_for"] = None
        data["follow_up_date"] = None
        return

    enters_waiting = (
        resulting_status == TaskStatus.waiting.value
        and current_status != TaskStatus.waiting.value
    )
    changes_waiting_fields = bool(
        resulting_status == TaskStatus.waiting.value
        and existing is not None
        and any(
            key in data and data[key] != getattr(existing, key)
            for key in ("waiting_for", "follow_up_date", "assigned_to")
        )
    )
    if not (enters_waiting or changes_waiting_fields):
        return

    waiting_for = data.get(
        "waiting_for", existing.waiting_for if existing is not None else None,
    )
    waiting_for = waiting_for.strip() if isinstance(waiting_for, str) else ""
    if not waiting_for:
        raise HTTPException(422, "Indica de qué respuesta externa está en espera la tarea")
    if enters_waiting or "waiting_for" in data:
        data["waiting_for"] = waiting_for

    follow_up_date = data.get(
        "follow_up_date",
        existing.follow_up_date if existing is not None else None,
    )
    if follow_up_date is None:
        raise HTTPException(422, "Indica una fecha de revisión para la espera")
    date_changed = bool(
        enters_waiting
        or (
            existing is not None
            and "follow_up_date" in data
            and data["follow_up_date"] != existing.follow_up_date
        )
    )
    if (
        date_changed
        and not allow_past_date
        and follow_up_date < business_today()
    ):
        raise HTTPException(422, "La fecha de revisión no puede estar en el pasado")

    assigned_to = data.get(
        "assigned_to", existing.assigned_to if existing is not None else None,
    )
    if assigned_to is None:
        raise HTTPException(422, "Asigna una persona responsable del siguiente paso")
    try:
        active_user = await db.scalar(
            select(User.id).where(
                User.id == assigned_to,
                User.is_active.is_(True),
            ).with_for_update(read=True, nowait=True)
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409,
                "La persona responsable está cambiando; vuelve a intentarlo",
            ) from exc
        raise
    if active_user is None:
        raise HTTPException(422, "La persona responsable no existe o está inactiva")


def stamp_task_status(task: Task, previous_status: TaskStatus | str | None = None) -> None:
    """Call after assigning a validated status; repeated completion keeps its date."""
    task.advanced_at = business_today() if task.status == TaskStatus.advanced else None
    if task.status == TaskStatus.completed and previous_status != TaskStatus.completed:
        task.completed_at = utc_now_naive()
    elif task.status != TaskStatus.completed and previous_status == TaskStatus.completed:
        task.completed_at = None
