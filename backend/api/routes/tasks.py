from __future__ import annotations
import logging
from datetime import date as date_type, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from backend.db.database import get_db
from backend.db.models import (
    Project,
    Task,
    TaskStatus,
    TaskPriority,
    User,
    UserRole,
    TaskChecklist,
    TaskComment,
    TaskAttachment,
)
from backend.schemas.task import (
    CarryoverDecisionRequest, TaskCreate, TaskRestoreRequest, TaskUpdate, TaskResponse,
)
from backend.schemas.task import RecurrencePreviewRequest, RecurrenceSummaryResponse
from backend.schemas.task_checklist import ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse
from backend.schemas.task_comment import TaskCommentCreate, TaskCommentResponse
from backend.schemas.task_attachment import TaskAttachmentResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module
from backend.api.utils.db_helpers import safe_refresh
from backend.api.middleware.audit_log import log_audit
from backend.services.temporal import civil_day_utc_bounds
from backend.services.time_entry_dates import manual_time_entry_date
from backend.services.domain_writes import (
    create_task as create_task_write, lock_task, lock_task_patch,
    update_task as update_task_write,
)
from backend.services.recurrence import summarize_recurrence
from backend.services.task_scope import validate_task_scope
from backend.services.temporal import business_today
from backend.services.task_retirement import (
    apply_carryover_decision, lock_task_for_cas, restore_task as restore_retired_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_TASK_RESPONSE_OPTIONS = (
    selectinload(Task.client),
    selectinload(Task.category),
    selectinload(Task.assigned_user),
    selectinload(Task.creator),
    selectinload(Task.project),
    selectinload(Task.phase),
    selectinload(Task.dependency),
    selectinload(Task.recurring_parent),
    selectinload(Task.checklist_items),
)


def _safe_attr(obj, rel: str, attr: str) -> str | None:
    """Safely get attribute from a relationship, None on any failure."""
    try:
        r = getattr(obj, rel, None)
        return getattr(r, attr) if r else None
    except Exception:
        return None


def _task_to_response(task: Task) -> TaskResponse:
    client_status = _safe_attr(task, "client", "status")
    project_status = _safe_attr(task, "project", "status")
    client_active = task.client_id is None or getattr(client_status, "value", client_status) == "active"
    project_active = task.project_id is None or getattr(project_status, "value", project_status) == "active"
    recurrence_summary = summarize_recurrence(
        is_recurring=task.is_recurring,
        pattern=task.recurrence_pattern,
        day=task.recurrence_day,
        anchor_date=task.recurrence_anchor_date,
        end_date=task.recurrence_end_date,
        paused=task.recurrence_paused_at is not None,
        client_active=client_active,
        project_active=project_active,
    )
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        estimated_minutes=task.estimated_minutes,
        actual_minutes=task.actual_minutes,
        due_date=task.due_date,
        client_id=task.client_id,
        category_id=task.category_id,
        assigned_to=task.assigned_to,
        project_id=task.project_id,
        phase_id=task.phase_id,
        depends_on=task.depends_on,
        created_by=task.created_by,
        scheduled_date=task.scheduled_date,
        waiting_for=task.waiting_for,
        follow_up_date=task.follow_up_date,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        retired_at=task.retired_at,
        retired_reason=task.retired_reason,
        is_recurring=task.is_recurring,
        recurrence_pattern=task.recurrence_pattern,
        recurrence_day=task.recurrence_day,
        recurrence_end_date=task.recurrence_end_date,
        recurrence_anchor_date=task.recurrence_anchor_date,
        recurrence_paused_at=task.recurrence_paused_at,
        recurrence_summary=RecurrenceSummaryResponse(**recurrence_summary.__dict__),
        recurring_parent_id=task.recurring_parent_id,
        recurrence_occurrence_date=task.recurrence_occurrence_date,
        unit_cost=float(task.unit_cost) if task.unit_cost is not None else None,
        invoiced_at=task.invoiced_at,
        link_url=task.link_url,
        client_name=_safe_attr(task, "client", "name"),
        category_name=_safe_attr(task, "category", "name"),
        assigned_user_name=_safe_attr(task, "assigned_user", "full_name"),
        project_name=_safe_attr(task, "project", "name"),
        phase_name=_safe_attr(task, "phase", "name"),
        dependency_title=_safe_attr(task, "dependency", "title"),
        created_by_name=_safe_attr(task, "creator", "full_name"),
        recurring_parent_title=_safe_attr(task, "recurring_parent", "title"),
        checklist_count=len(task.checklist_items) if task.checklist_items else 0,
    )


async def _load_task_for_response(db: AsyncSession, task_id: int) -> Task | None:
    result = await db.execute(
        select(Task)
        .options(*_TASK_RESPONSE_OPTIONS)
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _recurrence_delete_blocked(db: AsyncSession, task: Task) -> bool:
    if not task.is_recurring:
        return False
    from backend.db.models import TaskRecurrenceOccurrence
    child_id = (await db.execute(
        select(Task.id).where(Task.recurring_parent_id == task.id).limit(1)
    )).scalar_one_or_none()
    occurrence_id = (await db.execute(
        select(TaskRecurrenceOccurrence.id)
        .where(TaskRecurrenceOccurrence.template_id == task.id).limit(1)
    )).scalar_one_or_none()
    return child_id is not None or occurrence_id is not None


@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    client_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    category_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    assigned_to: Optional[str] = Query(None),
    priority: Optional[TaskPriority] = Query(None),
    overdue: Optional[bool] = Query(None),
    no_date: Optional[bool] = Query(None),
    no_estimate: Optional[bool] = Query(None),
    no_project: Optional[bool] = Query(None),
    scheduled_date: Optional[str] = Query(None),
    due_date_from: Optional[str] = Query(None),
    due_date_to: Optional[str] = Query(None),
    scheduled_date_from: Optional[str] = Query(None),
    scheduled_date_to: Optional[str] = Query(None),
    is_recurring: Optional[bool] = Query(None),
    retirement: Literal["active", "retired"] = Query("active"),
    search: Optional[str] = Query(None, description="Search tasks by title or description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_module("tasks")),
):
    base = select(Task).where(
        Task.retired_at.is_(None) if retirement == "active" else Task.retired_at.is_not(None)
    )
    if search is not None and search.strip():
        term = f"%{search.strip()}%"
        base = base.where(
            Task.title.ilike(term) | Task.description.ilike(term)
        )
    if client_id is not None:
        base = base.where(Task.client_id == client_id)
    if status_filter is not None:
        # Support comma-separated statuses: ?status=pending,in_progress,waiting
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        parsed_statuses = []
        for s in statuses:
            try:
                parsed_statuses.append(TaskStatus(s))
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid status: {s}")
        if len(parsed_statuses) == 1:
            base = base.where(Task.status == parsed_statuses[0])
        elif parsed_statuses:
            base = base.where(Task.status.in_(parsed_statuses))
    if category_id is not None:
        base = base.where(Task.category_id == category_id)
    if project_id is not None:
        base = base.where(Task.project_id == project_id)
    if assigned_to is not None:
        if assigned_to == "unassigned":
            base = base.where(Task.assigned_to.is_(None))
        elif assigned_to == "me":
            base = base.where(Task.assigned_to == current_user.id)
        else:
            try:
                base = base.where(Task.assigned_to == int(assigned_to))
            except ValueError:
                raise HTTPException(status_code=422, detail="assigned_to must be 'unassigned', 'me', or a valid user ID")
    if priority is not None:
        base = base.where(Task.priority == priority)
    if overdue:
        from datetime import date as _date
        base = base.where(
            Task.due_date < _date.today(),
            Task.status != TaskStatus.completed,
        )
    if no_date:
        base = base.where(Task.due_date.is_(None), Task.scheduled_date.is_(None))
    if no_estimate:
        base = base.where(Task.estimated_minutes.is_(None))
    if no_project:
        base = base.where(Task.project_id.is_(None))
    if scheduled_date is not None:
        from datetime import date as date_type
        try:
            sd = date_type.fromisoformat(scheduled_date)
            base = base.where(Task.scheduled_date == sd)
        except ValueError:
            raise HTTPException(status_code=422, detail="scheduled_date must be YYYY-MM-DD")
    if due_date_from is not None:
        from datetime import date as date_type
        try:
            d = date_type.fromisoformat(due_date_from)
            base = base.where(Task.due_date >= d)
        except ValueError:
            raise HTTPException(status_code=422, detail="due_date_from must be YYYY-MM-DD")
    if due_date_to is not None:
        from datetime import date as date_type
        try:
            d = date_type.fromisoformat(due_date_to)
            base = base.where(Task.due_date <= d)
        except ValueError:
            raise HTTPException(status_code=422, detail="due_date_to must be YYYY-MM-DD")
    if scheduled_date_from is not None:
        from datetime import date as date_type
        try:
            d = date_type.fromisoformat(scheduled_date_from)
            base = base.where(Task.scheduled_date >= d)
        except ValueError:
            raise HTTPException(status_code=422, detail="scheduled_date_from must be YYYY-MM-DD")
    if scheduled_date_to is not None:
        from datetime import date as date_type
        try:
            d = date_type.fromisoformat(scheduled_date_to)
            base = base.where(Task.scheduled_date <= d)
        except ValueError:
            raise HTTPException(status_code=422, detail="scheduled_date_to must be YYYY-MM-DD")

    # Recurring filter: by default exclude templates from normal views
    if is_recurring is True:
        base = base.where(Task.is_recurring == True)
    else:
        # Default + explicit false: hide templates
        base = base.where(Task.is_recurring == False)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    query = (
        base.options(*_TASK_RESPONSE_OPTIONS)
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)

    return PaginatedResponse(
        items=[_task_to_response(t) for t in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/agenda", response_model=PaginatedResponse[TaskResponse])
async def list_task_agenda(
    date: date_type = Query(...),
    section: Literal["planned", "carryover", "unplanned", "completed"] = Query(...),
    assigned_to: str = Query("me"),
    timezone_offset_minutes: int = Query(
        0, ge=-840, le=840, deprecated=True,
        description="Compatibilidad: Hoy usa AGENCY_TIMEZONE; este offset ya no altera el resultado.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_module("tasks")),
):
    """Return one explicitly paginated section of a user's civil-day agenda."""
    base = select(Task).where(Task.is_recurring.is_(False), Task.retired_at.is_(None))
    if assigned_to == "me":
        if section == "completed":
            base = base.where(Task.assigned_to == current_user.id)
        else:
            base = base.where(or_(Task.assigned_to == current_user.id, Task.assigned_to.is_(None)))
    elif assigned_to == "unassigned":
        base = base.where(Task.assigned_to.is_(None))
    elif assigned_to == "all":
        if current_user.role != UserRole.admin:
            raise HTTPException(status_code=403, detail="Admin required for team agenda")
    else:
        try:
            base = base.where(Task.assigned_to == int(assigned_to))
        except ValueError:
            raise HTTPException(status_code=422, detail="assigned_to must be 'me', 'unassigned', 'all', or a valid user ID")

    due_day = func.date(Task.due_date)
    if section == "planned":
        base = base.where(
            Task.status != TaskStatus.completed,
            or_(
                due_day == date,
                (Task.status != TaskStatus.waiting)
                & (Task.scheduled_date == date)
                & or_(Task.due_date.is_(None), due_day > date),
            ),
        )
    elif section == "carryover":
        base = base.where(
            Task.status != TaskStatus.completed,
            or_(
                due_day < date,
                (Task.status != TaskStatus.waiting)
                & (Task.scheduled_date < date)
                & or_(Task.due_date.is_(None), due_day != date),
            ),
        )
    elif section == "unplanned":
        base = base.where(
            Task.status != TaskStatus.completed,
            Task.status != TaskStatus.waiting,
            Task.scheduled_date.is_(None),
            or_(Task.due_date.is_(None), due_day > date),
        )
    else:
        utc_start, utc_end = civil_day_utc_bounds(date)
        base = base.where(
            Task.status == TaskStatus.completed,
            Task.completed_at >= utc_start,
            Task.completed_at < utc_end,
        )

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    query = (
        base.options(*_TASK_RESPONSE_OPTIONS)
        .order_by(Task.priority.asc(), Task.due_date.asc().nullslast(), Task.created_at.asc(), Task.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    return PaginatedResponse(
        items=[_task_to_response(task) for task in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    data = body.model_dump()
    try:
        task = await create_task_write(
            db, data, actor=current_user, manual_entry_date=manual_time_entry_date(),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al crear tarea (datos duplicados o referencia inválida)")
    except DataError as e:
        await db.rollback()
        logger.warning("DataError creando tarea: %s", e)
        raise HTTPException(status_code=422, detail="Datos inválidos: uno o más campos exceden la longitud máxima")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Error creando tarea: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    task = await _load_task_for_response(db, task.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found after create")

    # Notify assignee (non-critical — don't fail the whole request)
    if body.assigned_to:
        try:
            from backend.services.notification_service import create_notification, TASK_ASSIGNED
            await create_notification(
                db,
                user_id=body.assigned_to,
                type=TASK_ASSIGNED,
                title=f"Nueva tarea asignada: {task.title}",
                message=f"Se te ha asignado la tarea '{task.title}'",
                link_url="/tasks",
                entity_type="task",
                entity_id=task.id,
            )
            await db.commit()
        except Exception:
            logger.warning("Non-critical: notification failed after task creation for task_id=%s", task.id)
            try:
                await db.rollback()
            except Exception:
                pass

    log_audit(current_user.id, "create", "task", task.id, details=f"title={task.title}")
    return _task_to_response(task)


@router.post("/recurrence-preview", response_model=RecurrenceSummaryResponse)
async def preview_recurrence(
    body: RecurrencePreviewRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    """Validate and preview a recurrence without persisting anything."""
    scope = {
        "client_id": body.client_id,
        "project_id": body.project_id,
        "phase_id": body.phase_id,
    }
    await validate_task_scope(db, scope)
    client_active = True
    project_active = True
    if scope.get("client_id") is not None:
        from backend.db.models import Client, ClientStatus
        client_status = (await db.execute(select(Client.status).where(Client.id == scope["client_id"]))).scalar_one()
        client_active = client_status == ClientStatus.active
    if scope.get("project_id") is not None:
        from backend.db.models import ProjectStatus
        project_status = (await db.execute(select(Project.status).where(Project.id == scope["project_id"]))).scalar_one()
        project_active = project_status == ProjectStatus.active
    anchor = body.recurrence_anchor_date
    if (body.is_recurring and body.recurrence_pattern == "biweekly"
            and "recurrence_anchor_date" not in body.model_fields_set):
        anchor = business_today()
    summary = summarize_recurrence(
        is_recurring=body.is_recurring,
        pattern=body.recurrence_pattern,
        day=body.recurrence_day,
        anchor_date=anchor,
        end_date=body.recurrence_end_date,
        paused=body.recurrence_paused,
        client_active=client_active,
        project_active=project_active,
    )
    if summary.state == "invalid":
        raise HTTPException(422, summary.reason)
    return RecurrenceSummaryResponse(**summary.__dict__)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    result = await db.execute(
        select(Task)
        .options(*_TASK_RESPONSE_OPTIONS)
        .where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    update_data = body.model_dump(exclude_unset=True)
    # Serialize all task edits before comparing or deriving actual_minutes.
    # Without this lock, two concurrent explicit total edits can both observe
    # the old total and each create the same manual adjustment.
    # Dependency changes lock both ids in order, avoiding A→B / B→A deadlocks.
    task = await lock_task_patch(db, task_id, update_data)
    old_assigned_to = task.assigned_to
    old_status = task.status.value if hasattr(task.status, "value") else str(task.status)
    try:
        task = await update_task_write(
            db, task, update_data, actor=current_user,
            manual_entry_date=manual_time_entry_date(),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al actualizar tarea")
    except DataError as e:
        await db.rollback()
        logger.warning("DataError actualizando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=422, detail="Datos inválidos: uno o más campos exceden la longitud máxima")
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Error actualizando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    # Automation hook: task_completed
    new_status = update_data.get("status")
    if new_status and str(new_status) == "completed" and old_status != "completed":
        try:
            from backend.api.routes.automations import execute_automations
            await execute_automations("task_completed", {
                "task_id": task_id,
                "task_title": task.title,
                "project_id": task.project_id,
                "client_id": task.client_id,
                "phase_id": task.phase_id,
                "assigned_to": task.assigned_to,
                "old_status": old_status,
            }, db)
        except Exception as e:
            logger.warning("Automation hook failed for task %d: %s", task_id, e)

    task = await _load_task_for_response(db, task.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found after update")

    # Notify new assignee if assignment changed
    update_data = body.model_dump(exclude_unset=True)
    new_assigned = update_data.get("assigned_to")
    if new_assigned and new_assigned != old_assigned_to:
        try:
            from backend.services.notification_service import create_notification, TASK_ASSIGNED
            await create_notification(
                db,
                user_id=new_assigned,
                type=TASK_ASSIGNED,
                title=f"Tarea asignada: {task.title}",
                message=f"Se te ha reasignado la tarea '{task.title}'",
                link_url="/tasks",
                entity_type="task",
                entity_id=task.id,
            )
            await db.commit()
        except Exception:
            logger.warning("Non-critical: notification failed after task update for task_id=%s", task.id)
            try:
                await db.rollback()
            except Exception:
                pass

    return _task_to_response(task)


@router.post("/{task_id}/carryover-decision", response_model=TaskResponse)
async def decide_carryover(
    task_id: int,
    body: CarryoverDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    task = await lock_task_for_cas(db, task_id, body.expected_updated_at)
    await apply_carryover_decision(
        db, task, body.model_dump(exclude={"expected_updated_at"}), actor=current_user,
    )
    await db.commit()
    loaded = await _load_task_for_response(db, task_id)
    if loaded is None:
        raise HTTPException(404, "Task not found after carryover decision")
    return _task_to_response(loaded)


@router.post("/{task_id}/restore", response_model=TaskResponse)
async def restore_task(
    task_id: int,
    body: TaskRestoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    task = await lock_task_for_cas(
        db, task_id, body.expected_updated_at, lock_dependency=True,
    )
    await restore_retired_task(db, task, actor=current_user)
    await db.commit()
    loaded = await _load_task_for_response(db, task_id)
    if loaded is None:
        raise HTTPException(404, "Task not found after restore")
    return _task_to_response(loaded)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks", write=True)),
):
    result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.is_recurring:
        if await _recurrence_delete_blocked(db, task):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta plantilla ya generó tareas. Páusala o fija una fecha de fin para conservar el historial.",
            )
    try:
        await db.delete(task)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede eliminar: tiene registros asociados")
    except Exception as e:
        await db.rollback()
        logger.error("Error eliminando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    log_audit(_.id, "delete", "task", task_id)


# ── Bulk operations ──────────────────────────────────────────────────────────

class BulkUpdateBody(BaseModel):
    ids: list[int]
    updates: dict  # Partial task fields: status, priority, assigned_to, etc.

class BulkDeleteBody(BaseModel):
    ids: list[int]


@router.patch("/bulk/update")
async def bulk_update_tasks(
    body: BulkUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    if not body.ids or len(body.ids) > 100:
        raise HTTPException(400, "Provide 1-100 task IDs")
    allowed = {"status", "priority", "assigned_to", "category_id", "due_date", "client_id", "project_id", "phase_id"}
    updates = {k: v for k, v in body.updates.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    dependency_snapshot: dict[int, int | None] = {}
    try:
        requested_status = TaskStatus(updates["status"]) if updates.get("status") else None
    except ValueError:
        requested_status = None
    if requested_status is not None and requested_status != TaskStatus.completed:
        dependency_snapshot = dict((await db.execute(
            select(Task.id, Task.depends_on).where(Task.id.in_(body.ids))
        )).all())
    requested_ids = set(body.ids)
    lock_ids = set(requested_ids)
    lock_ids.update(value for value in dependency_snapshot.values() if value is not None)

    result = await db.execute(
        select(Task).where(Task.id.in_(lock_ids)).order_by(Task.id)
        .options(noload("*")).with_for_update()
        .execution_options(populate_existing=True)
    )
    locked = {task.id: task for task in result.scalars().all()}
    tasks = [locked[task_id] for task_id in sorted(requested_ids) if task_id in locked]
    if any(task.depends_on != dependency_snapshot[task.id] for task in tasks if task.id in dependency_snapshot):
        raise HTTPException(409, "La dependencia cambió; vuelve a intentarlo")
    updated = 0
    failed = 0
    for task in tasks:
        try:
            async with db.begin_nested():
                scoped_updates = dict(updates)
                if "status" in scoped_updates and scoped_updates["status"]:
                    scoped_updates["status"] = TaskStatus(scoped_updates["status"])
                if "priority" in scoped_updates and scoped_updates["priority"]:
                    scoped_updates["priority"] = TaskPriority(scoped_updates["priority"])
                await update_task_write(db, task, scoped_updates, actor=current_user)
            updated += 1
        except Exception as e:
            failed += 1
            logger.warning("bulk_update_tasks: skipped task %s: %s", task.id, e)
    await db.commit()
    return {"updated": updated, "failed": failed, "requested": len(body.ids)}


@router.post("/bulk/delete")
async def bulk_delete_tasks(
    body: BulkDeleteBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks", write=True)),
):
    if not body.ids or len(body.ids) > 100:
        raise HTTPException(400, "Provide 1-100 task IDs")
    result = await db.execute(
        select(Task).where(Task.id.in_(body.ids)).order_by(Task.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    tasks = result.scalars().all()
    deleted = 0
    skipped_ids: list[int] = []
    recurrence_skipped_ids: list[int] = []
    for task in tasks:
        if await _recurrence_delete_blocked(db, task):
            skipped_ids.append(task.id)
            recurrence_skipped_ids.append(task.id)
            continue
        try:
            async with db.begin_nested():
                await db.delete(task)
                await db.flush()
            deleted += 1
        except IntegrityError:
            skipped_ids.append(task.id)
        except Exception:
            skipped_ids.append(task.id)
    if deleted:
        try:
            await db.commit()
        except Exception as exc:
            logger.error("bulk_delete_tasks: commit failed; no deletion confirmed: %s", exc)
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail="No se pudo confirmar el borrado; no se ha marcado ninguna tarea como eliminada",
            )
    detail = None
    if recurrence_skipped_ids:
        detail = (
            f"No se pudieron eliminar {len(recurrence_skipped_ids)} plantillas porque ya generaron tareas. "
            "Páusalas o fija una fecha de fin para conservar el historial."
        )
    elif skipped_ids:
        detail = f"No se pudieron eliminar {len(skipped_ids)} tareas porque tienen registros de tiempo asociados. Elimínalos primero."
    return {"deleted": deleted, "errors": len(skipped_ids), "requested": len(body.ids), "detail": detail}


# ── Checklist endpoints ───────────────────────────────────────────────────────


def _checklist_response(item: TaskChecklist) -> ChecklistItemResponse:
    return ChecklistItemResponse(
        id=item.id,
        task_id=item.task_id,
        text=item.text,
        description=item.description,
        is_done=item.is_done,
        order_index=item.order_index,
        assigned_to=item.assigned_to,
        due_date=item.due_date,
        assigned_user_name=item.assigned_user.full_name if item.assigned_user else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/{task_id}/checklist", response_model=list[ChecklistItemResponse])
async def list_checklist(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks")),
):
    r = await db.execute(
        select(TaskChecklist)
        .options(selectinload(TaskChecklist.assigned_user))
        .where(TaskChecklist.task_id == task_id)
        .order_by(TaskChecklist.order_index)
    )
    return [_checklist_response(i) for i in r.scalars().all()]


@router.post("/{task_id}/checklist", response_model=ChecklistItemResponse, status_code=201)
async def create_checklist_item(
    task_id: int,
    data: ChecklistItemCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    task = await lock_task(db, task_id)
    if task.retired_at is not None:
        raise HTTPException(409, "Restaura la tarea antes de modificar su checklist")
    item = TaskChecklist(task_id=task_id, **data.model_dump())
    db.add(item)
    await db.commit()
    await safe_refresh(db, item, log_context="tasks")
    return _checklist_response(item)


@router.put("/{task_id}/checklist/{item_id}", response_model=ChecklistItemResponse)
async def update_checklist_item(
    task_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    task = await lock_task(db, task_id)
    if task.retired_at is not None:
        raise HTTPException(409, "Restaura la tarea antes de modificar su checklist")
    r = await db.execute(
        select(TaskChecklist).where(TaskChecklist.id == item_id, TaskChecklist.task_id == task_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await safe_refresh(db, item, log_context="tasks")
    return _checklist_response(item)


@router.delete("/{task_id}/checklist/{item_id}", status_code=204)
async def delete_checklist_item(
    task_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    task = await lock_task(db, task_id)
    if task.retired_at is not None:
        raise HTTPException(409, "Restaura la tarea antes de modificar su checklist")
    r = await db.execute(
        select(TaskChecklist).where(TaskChecklist.id == item_id, TaskChecklist.task_id == task_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    await db.delete(item)
    await db.commit()


# ── Comment endpoints ────────────────────────────────────────────────────────

@router.get("/{task_id}/comments", response_model=list[TaskCommentResponse])
async def list_comments(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    r = await db.execute(
        select(TaskComment)
        .options(selectinload(TaskComment.user))
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc())
    )
    return [
        TaskCommentResponse(
            id=c.id, task_id=c.task_id, user_id=c.user_id, text=c.text,
            user_name=c.user.full_name if c.user else None,
            created_at=c.created_at, updated_at=c.updated_at,
        )
        for c in r.scalars().all()
    ]


@router.post("/{task_id}/comments", response_model=TaskCommentResponse, status_code=201)
async def create_comment(
    task_id: int,
    body: TaskCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    # Verify task exists
    t = await db.execute(select(Task.id).where(Task.id == task_id))
    if not t.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")
    comment = TaskComment(task_id=task_id, user_id=current_user.id, text=body.text)
    db.add(comment)
    await db.commit()
    await safe_refresh(db, comment, log_context="tasks")
    return TaskCommentResponse(
        id=comment.id, task_id=comment.task_id, user_id=comment.user_id,
        text=comment.text, user_name=current_user.full_name,
        created_at=comment.created_at, updated_at=comment.updated_at,
    )


@router.delete("/{task_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    task_id: int,
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    r = await db.execute(
        select(TaskComment).where(TaskComment.id == comment_id, TaskComment.task_id == task_id)
    )
    comment = r.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Only author or admin can delete
    if comment.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este comentario")
    await db.delete(comment)
    await db.commit()


# ── Attachment endpoints ─────────────────────────────────────────────────────

@router.get("/{task_id}/attachments", response_model=list[TaskAttachmentResponse])
async def list_attachments(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    r = await db.execute(
        select(TaskAttachment)
        .options(selectinload(TaskAttachment.uploader))
        .where(TaskAttachment.task_id == task_id)
        .order_by(TaskAttachment.created_at.desc())
    )
    return [
        TaskAttachmentResponse(
            id=a.id, task_id=a.task_id, name=a.name, description=a.description,
            mime_type=a.mime_type, size_bytes=a.size_bytes,
            uploaded_by=a.uploaded_by,
            uploaded_by_name=a.uploader.full_name if a.uploader else None,
            created_at=a.created_at, updated_at=a.updated_at,
        )
        for a in r.scalars().all()
    ]


from fastapi import UploadFile, File as FileParam


ALLOWED_ATTACHMENT_MIME = {"application/pdf", "image/png", "image/jpeg", "image/gif", "text/plain", "text/csv",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/{task_id}/attachments", response_model=TaskAttachmentResponse, status_code=201)
async def upload_task_attachment(
    task_id: int,
    file: UploadFile = FileParam(...),
    description: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    # Verify task exists
    t = await db.execute(select(Task.id).where(Task.id == task_id))
    if not t.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")
    # Validate MIME type
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_ATTACHMENT_MIME:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
    # Validate size
    content = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Adjunto demasiado grande (máx 10 MB)")
    # Deduplicate filename
    original_name = file.filename or "file"
    existing = await db.execute(
        select(TaskAttachment.name).where(TaskAttachment.task_id == task_id)
    )
    existing_names = {r[0] for r in existing.all()}
    final_name = original_name
    if final_name in existing_names:
        import os
        base, ext = os.path.splitext(original_name)
        counter = 1
        while final_name in existing_names:
            final_name = f"{base} ({counter}){ext}"
            counter += 1
    attachment = TaskAttachment(
        task_id=task_id,
        name=final_name,
        description=description or None,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        content=content,
        uploaded_by=current_user.id,
    )
    db.add(attachment)
    await db.commit()
    await safe_refresh(db, attachment, log_context="tasks")
    return TaskAttachmentResponse(
        id=attachment.id, task_id=attachment.task_id, name=attachment.name,
        description=attachment.description, mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes, uploaded_by=attachment.uploaded_by,
        uploaded_by_name=current_user.full_name,
        created_at=attachment.created_at, updated_at=attachment.updated_at,
    )


@router.get("/{task_id}/attachments/{attachment_id}/download")
async def download_attachment(
    task_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    from fastapi.responses import Response
    r = await db.execute(
        select(TaskAttachment)
        .where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == task_id)
    )
    att = r.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return Response(
        content=att.content,
        media_type=att.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{att.name.replace(chr(34), "_").replace(chr(10), "_").replace(chr(13), "_")}"'},
    )


@router.get("/{task_id}/attachments/{attachment_id}/preview")
async def preview_attachment(
    task_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks")),
):
    """Serve attachment inline for browser preview (images, PDFs)."""
    from fastapi.responses import Response
    r = await db.execute(
        select(TaskAttachment)
        .where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == task_id)
    )
    att = r.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    safe_name = att.name.replace('"', '_').replace('\n', '_').replace('\r', '_')
    return Response(
        content=att.content,
        media_type=att.mime_type,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.delete("/{task_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    task_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    r = await db.execute(
        select(TaskAttachment)
        .where(TaskAttachment.id == attachment_id, TaskAttachment.task_id == task_id)
    )
    att = r.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if att.uploaded_by != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este adjunto")
    await db.delete(att)
    await db.commit()
