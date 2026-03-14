from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Task, TaskStatus, TaskPriority, User, TaskChecklist, TaskComment, TaskAttachment
from backend.schemas.task import TaskCreate, TaskUpdate, TaskResponse
from backend.schemas.task_checklist import ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse
from backend.schemas.task_comment import TaskCommentCreate, TaskCommentResponse
from backend.schemas.task_attachment import TaskAttachmentResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module

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


def _task_to_response(task: Task) -> TaskResponse:
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
        is_recurring=task.is_recurring,
        recurrence_pattern=task.recurrence_pattern,
        recurrence_day=task.recurrence_day,
        recurrence_end_date=task.recurrence_end_date,
        recurring_parent_id=task.recurring_parent_id,
        client_name=task.client.name if task.client else None,
        category_name=task.category.name if task.category else None,
        assigned_user_name=task.assigned_user.full_name if task.assigned_user else None,
        project_name=task.project.name if task.project else None,
        phase_name=task.phase.name if task.phase else None,
        dependency_title=task.dependency.title if task.dependency else None,
        created_by_name=task.creator.full_name if task.creator else None,
        recurring_parent_title=task.recurring_parent.title if task.recurring_parent else None,
        checklist_count=len(task.checklist_items) if task.checklist_items else 0,
    )


async def _load_task_for_response(db: AsyncSession, task_id: int) -> Task | None:
    result = await db.execute(
        select(Task)
        .options(*_TASK_RESPONSE_OPTIONS)
        .where(Task.id == task_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    client_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    category_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    assigned_to: Optional[str] = Query(None),
    priority: Optional[TaskPriority] = Query(None),
    overdue: Optional[bool] = Query(None),
    scheduled_date: Optional[str] = Query(None),
    is_recurring: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_module("tasks")),
):
    base = select(Task)
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
        from datetime import datetime
        base = base.where(
            Task.due_date < datetime.utcnow(),
            Task.status != TaskStatus.completed,
        )
    if scheduled_date is not None:
        from datetime import date as date_type
        try:
            sd = date_type.fromisoformat(scheduled_date)
            base = base.where(Task.scheduled_date == sd)
        except ValueError:
            raise HTTPException(status_code=422, detail="scheduled_date must be YYYY-MM-DD")

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


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("tasks", write=True)),
):
    task = Task(**body.model_dump(), created_by=current_user.id)
    db.add(task)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al crear tarea (datos duplicados o referencia inválida)")
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
            logger.exception("Error sending task notification for task_id=%s", task.id)

    return _task_to_response(task)


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
    _: User = Depends(require_module("tasks", write=True)),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    old_assigned_to = task.assigned_to
    # actual_minutes excluded: auto-synced from time entries, not manually editable
    _UPDATABLE_TASK_FIELDS = {
        "title", "description", "status", "priority", "estimated_minutes",
        "start_date", "due_date", "client_id", "category_id",
        "assigned_to", "project_id", "phase_id", "depends_on",
        "scheduled_date", "waiting_for", "follow_up_date",
        "is_recurring", "recurrence_pattern", "recurrence_day",
        "recurrence_end_date", "recurring_parent_id",
    }
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in _UPDATABLE_TASK_FIELDS:
            setattr(task, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al actualizar tarea")
    except Exception as e:
        await db.rollback()
        logger.error("Error actualizando tarea %d: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
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
        except Exception as e:
            logger.warning("Failed to send assignment notification for task %d: %s", task.id, e)

    return _task_to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks", write=True)),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
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
    _: User = Depends(require_module("tasks", write=True)),
):
    if not body.ids or len(body.ids) > 100:
        raise HTTPException(400, "Provide 1-100 task IDs")
    allowed = {"status", "priority", "assigned_to", "category_id", "due_date", "client_id", "project_id", "phase_id"}
    updates = {k: v for k, v in body.updates.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    result = await db.execute(select(Task).where(Task.id.in_(body.ids)))
    tasks = result.scalars().all()
    updated = 0
    for task in tasks:
        for field, value in updates.items():
            if field == "status" and value:
                value = TaskStatus(value)
            if field == "priority" and value:
                value = TaskPriority(value)
            setattr(task, field, value)
        updated += 1
    await db.commit()
    return {"updated": updated, "requested": len(body.ids)}


@router.post("/bulk/delete")
async def bulk_delete_tasks(
    body: BulkDeleteBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("tasks", write=True)),
):
    if not body.ids or len(body.ids) > 100:
        raise HTTPException(400, "Provide 1-100 task IDs")
    result = await db.execute(select(Task).where(Task.id.in_(body.ids)))
    tasks = result.scalars().all()
    deleted = 0
    skipped_ids: list[int] = []
    for task in tasks:
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
        await db.commit()
    detail = None
    if skipped_ids:
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
    item = TaskChecklist(task_id=task_id, **data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _checklist_response(item)


@router.put("/{task_id}/checklist/{item_id}", response_model=ChecklistItemResponse)
async def update_checklist_item(
    task_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    r = await db.execute(
        select(TaskChecklist).where(TaskChecklist.id == item_id, TaskChecklist.task_id == task_id)
    )
    item = r.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return _checklist_response(item)


@router.delete("/{task_id}/checklist/{item_id}", status_code=204)
async def delete_checklist_item(
    task_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("tasks", write=True)),
):
    r = await db.execute(
        select(TaskChecklist).where(TaskChecklist.id == item_id, TaskChecklist.task_id == task_id)
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
    await db.refresh(comment)
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
    await db.refresh(attachment)
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
