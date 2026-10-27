"""Avisos de actividad sobre tareas en la campana (pestaña Actividad).

Comentarios, @menciones, revisión y "vence mañana". Reglas comunes:

- Sólo a personas activas que hoy pueden leer Tareas (la campana además los
  esconde si pierden ese permiso o se borra la tarea:
  ``notification_checks.visible_notification_condition``).
- Nunca a quien hace el cambio, y una sola fila por persona y acción.
- No hacen commit: van en la transacción del cambio que los provoca.
- Enlazan a la tarea (``/tasks?task=ID``), que abre su panel.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.modules import is_enabled
from backend.db.models import (
    Notification, Project, Task, TaskComment, TaskStatus, User, UserPermission, UserRole,
)
from backend.services.temporal import business_today

TASK_COMMENT = "task_comment"
TASK_MENTION = "task_mention"
TASK_REVIEW_REQUESTED = "task_review_requested"
TASK_REVIEW_APPROVED = "task_review_approved"
TASK_REVIEW_RETURNED = "task_review_returned"
TASK_DUE_TOMORROW = "task_due_tomorrow"

#: Tipos que la campana enseña mientras se pueda leer la tarea.
TASK_ACTIVITY_TYPES = (
    TASK_COMMENT, TASK_MENTION, TASK_REVIEW_REQUESTED, TASK_REVIEW_APPROVED,
    TASK_REVIEW_RETURNED, TASK_DUE_TOMORROW,
)

_STATUS_LABELS = {
    TaskStatus.backlog: "Pendiente",
    TaskStatus.pending: "Pendiente",
    TaskStatus.in_progress: "En curso",
    TaskStatus.advanced: "En curso",
    TaskStatus.waiting: "En espera",
}


def task_link(task_id: int) -> str:
    return f"/tasks?task={task_id}"


def _can_read_tasks():
    return or_(User.role == UserRole.admin, exists().where(
        UserPermission.user_id == User.id,
        UserPermission.module == "tasks",
        UserPermission.can_read.is_(True),
    ))


async def task_readers(db: AsyncSession, user_ids: Iterable[int | None], *, exclude: int | None) -> list[int]:
    """De ``user_ids``, quienes están activos y pueden leer Tareas, en orden de id."""
    ids = {user_id for user_id in user_ids if user_id is not None and user_id != exclude}
    if not ids or not is_enabled("tasks"):
        return []
    rows = await db.execute(
        select(User.id).where(User.id.in_(ids), User.is_active.is_(True), _can_read_tasks()).order_by(User.id)
    )
    return list(rows.scalars())


def _name(user: User | None) -> str:
    if user is None:
        return "Alguien"
    return user.short_name or user.full_name or "Alguien"


def _add(db: AsyncSession, user_ids: Iterable[int], *, type: str, task: Task, title: str, message: str | None):
    for user_id in user_ids:
        db.add(Notification(
            user_id=user_id, type=type, title=title[:255], message=message,
            link_url=task_link(task.id), entity_type="task", entity_id=task.id,
        ))


def _excerpt(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


async def notify_task_comment(
    db: AsyncSession, task: Task, comment: TaskComment, actor: User, mention_ids: Iterable[int] = (),
) -> None:
    """Mencionados: "te ha mencionado". Responsable y quien ya comentó: "ha comentado"."""
    mentioned = await task_readers(db, mention_ids, exclude=actor.id)
    previous = (await db.execute(
        select(TaskComment.user_id).where(
            TaskComment.task_id == task.id, TaskComment.id != comment.id,
            TaskComment.is_ai_draft.is_(False),
        ).distinct()
    )).scalars().all()
    followers = [
        user_id for user_id in await task_readers(db, [task.assigned_to, *previous], exclude=actor.id)
        if user_id not in mentioned
    ]
    who = _name(actor)
    excerpt = _excerpt(comment.text)
    _add(db, mentioned, type=TASK_MENTION, task=task,
         title=f"{who} te ha mencionado en «{task.title}»", message=excerpt)
    _add(db, followers, type=TASK_COMMENT, task=task,
         title=f"{who} ha comentado en «{task.title}»", message=excerpt)


def _status(value) -> TaskStatus | None:
    if value is None:
        return None
    return value if isinstance(value, TaskStatus) else TaskStatus(value)


async def notify_task_status_change(db: AsyncSession, task: Task, old_status, actor: User | None) -> None:
    """Pedir revisión avisa a quien puede cerrarla; cerrarla o devolverla, al responsable."""
    old, new = _status(old_status), _status(task.status)
    if actor is None or old == new:
        return
    who = _name(actor)
    if new == TaskStatus.in_review:
        owner_id = None
        if task.project_id is not None:
            owner_id = await db.scalar(select(Project.owner_id).where(Project.id == task.project_id))
        admins = (await db.execute(
            select(User.id).where(User.role == UserRole.admin, User.is_active.is_(True))
        )).scalars().all()
        reviewers = await task_readers(db, [owner_id, *admins], exclude=actor.id)
        _add(db, reviewers, type=TASK_REVIEW_REQUESTED, task=task,
             title=f"«{task.title}» espera revisión", message=f"{who} la ha enviado a revisión.")
        return
    if old != TaskStatus.in_review:
        return
    assignee = await task_readers(db, [task.assigned_to], exclude=actor.id)
    if new == TaskStatus.completed:
        _add(db, assignee, type=TASK_REVIEW_APPROVED, task=task,
             title=f"Revisión aprobada: «{task.title}»", message=f"{who} la ha dado por hecha.")
    else:
        _add(db, assignee, type=TASK_REVIEW_RETURNED, task=task,
             title=f"«{task.title}» vuelve de revisión",
             message=f"{who} la ha devuelto a {_STATUS_LABELS.get(new, 'otro estado')}.")


async def notify_due_tomorrow(db: AsyncSession) -> int:
    """Una vez por tarea y fecha límite: tareas abiertas propias que vencen mañana.

    La clave (``dedupe_key`` con el día) hace que repetir la pasada, o
    arrancar dos veces el mismo día, no duplique nada. Devuelve cuántos crea.
    """
    if not is_enabled("tasks"):
        return 0
    tomorrow = business_today() + timedelta(days=1)
    start = datetime.combine(tomorrow, time.min)
    rows = (await db.execute(
        select(Task.id, Task.title, Task.assigned_to)
        .join(User, User.id == Task.assigned_to)
        .where(
            Task.due_date >= start, Task.due_date < start + timedelta(days=1),
            Task.status != TaskStatus.completed,
            Task.retired_at.is_(None),
            Task.is_recurring.is_(False),
            User.is_active.is_(True), _can_read_tasks(),
        )
        .order_by(Task.id)
    )).all()
    if not rows:
        return 0
    result = await db.execute(
        insert(Notification)
        .values([
            {
                "user_id": row.assigned_to, "type": TASK_DUE_TOMORROW,
                "title": f"«{row.title}» vence mañana"[:255],
                "message": "Tiene la fecha límite mañana y aún no está hecha.",
                "link_url": task_link(row.id), "entity_type": "task", "entity_id": row.id,
                "dedupe_key": f"{TASK_DUE_TOMORROW}:task:{row.id}:{tomorrow.isoformat()}",
            }
            for row in rows
        ])
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return len(result.all())
