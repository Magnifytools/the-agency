"""Inbox quick-capture API endpoints."""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from sqlalchemy import DateTime, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    InboxNote, InboxNoteStatus, InboxAttachment, Project, ProjectStatus, Client, ClientStatus,
    Task, TaskStatus, TaskPriority,
)
from backend.api.deps import get_current_user, require_module
from backend.api.utils.db_helpers import safe_refresh
from backend.schemas.inbox import (
    InboxNoteCreate, InboxNoteUpdate, InboxNoteResponse, ConvertToTaskBody,
)
from backend.core.rate_limiter import ai_limiter
from backend.services.task_scope import validate_task_scope
from backend.services.domain_writes import create_task as create_task_write
from backend.services.inbox_processing import can_read as _can_read
from backend.services.temporal import as_utc_instant, business_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _updated_clock():
    return func.clock_timestamp().cast(DateTime(timezone=False))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_rel_name(obj, rel_attr: str) -> str | None:
    """Safely get .name from a relationship, returning None on any error."""
    try:
        rel = getattr(obj, rel_attr, None)
        return rel.name if rel else None
    except Exception:
        return None


def _visible_suggestion(note: InboxNote, user=None) -> dict | None:
    suggestion = dict(note.ai_suggestion) if note.ai_suggestion else None
    if suggestion is not None:
        required_modules = suggestion.pop("_context_modules", None)
        if required_modules is None:
            # Legacy suggestions have no trustworthy record of what context was
            # sent to the provider, so expose them only with both permissions.
            required_modules = ["projects", "clients"]
        if user is not None and any(not _can_read(user, module) for module in required_modules):
            return None
    return suggestion


def _to_response(note: InboxNote, user=None) -> InboxNoteResponse:
    """Convert ORM model using the actor's current association permissions."""
    can_see_projects = user is None or _can_read(user, "projects")
    can_see_clients = user is None or _can_read(user, "clients")
    return InboxNoteResponse(
        id=note.id,
        user_id=note.user_id,
        raw_text=note.raw_text,
        source=note.source,
        status=note.status,
        project_id=note.project_id if can_see_projects else None,
        client_id=note.client_id if can_see_clients else None,
        project_name=_safe_rel_name(note, "project") if can_see_projects else None,
        client_name=_safe_rel_name(note, "client") if can_see_clients else None,
        resolved_as=note.resolved_as,
        resolved_entity_id=note.resolved_entity_id,
        ai_suggestion=_visible_suggestion(note, user),
        classification_error_code=note.classification_error_code,
        classification_next_attempt_at=as_utc_instant(note.classification_next_attempt_at),
        link_url=note.link_url,
        attachments=[
            {"id": a.id, "name": a.name, "mime_type": a.mime_type, "size_bytes": a.size_bytes}
            for a in (note.attachments or [])
        ],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def _get_note_or_404(
    note_id: int, user_id: int, db: AsyncSession,
) -> InboxNote:
    """Fetch an inbox note ensuring ownership."""
    result = await db.execute(
        select(InboxNote).where(InboxNote.id == note_id, InboxNote.user_id == user_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    return note


async def _validate_associations(db, user, project_id, client_id) -> None:
    project = None
    client = None
    if project_id is not None:
        if not _can_read(user, "projects"):
            raise HTTPException(status_code=403, detail="Sin permiso para consultar proyectos")
        project = await db.get(Project, project_id, populate_existing=True)
        if project is None or project.status != ProjectStatus.active:
            raise HTTPException(status_code=422, detail="El proyecto no está activo")
        parent_client = await db.get(Client, project.client_id, populate_existing=True)
        if parent_client is None or parent_client.status != ClientStatus.active:
            raise HTTPException(status_code=422, detail="El cliente del proyecto no está activo")
    if client_id is not None:
        if not _can_read(user, "clients"):
            raise HTTPException(status_code=403, detail="Sin permiso para consultar clientes")
        client = await db.get(Client, client_id, populate_existing=True)
        if client is None or client.status != ClientStatus.active:
            raise HTTPException(status_code=422, detail="El cliente no está activo")
    if project is not None and client is not None and project.client_id != client.id:
        raise HTTPException(status_code=422, detail="El proyecto no pertenece al cliente indicado")


# ---------------------------------------------------------------------------
# POST / — Create note
# ---------------------------------------------------------------------------

@router.post("", response_model=InboxNoteResponse, status_code=201)
async def create_inbox_note(
    body: InboxNoteCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Persist a quick note; durable background processing classifies it."""
    text = body.raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El texto no puede estar vacio")

    # If user already assigned project/client, skip AI classification
    already_assigned = body.project_id is not None or body.client_id is not None
    initial_status = InboxNoteStatus.classified if already_assigned else InboxNoteStatus.pending
    await _validate_associations(db, user, body.project_id, body.client_id)

    note = InboxNote(
        user_id=user.id,
        raw_text=text,
        source=body.source,
        project_id=body.project_id,
        client_id=body.client_id,
        link_url=body.link_url,
        status=initial_status,
    )
    db.add(note)
    await db.commit()
    await safe_refresh(db, note, log_context="create_inbox_note")

    return _to_response(note, user)


# ---------------------------------------------------------------------------
# GET / — List notes
# ---------------------------------------------------------------------------

@router.get("")
async def list_inbox_notes(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[InboxNoteResponse]:
    """List inbox notes for the current user, optionally filtered by status."""
    q = select(InboxNote).where(InboxNote.user_id == user.id)

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        valid = [s for s in statuses if s in InboxNoteStatus.__members__]
        if valid:
            q = q.where(InboxNote.status.in_(valid))

    q = q.order_by(InboxNote.created_at.desc(), InboxNote.id.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return [_to_response(n, user) for n in result.scalars().all()]


# ---------------------------------------------------------------------------
# GET /count — Unprocessed count (for sidebar badge)
# ---------------------------------------------------------------------------

@router.get("/count")
async def inbox_count(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Get count of pending + classified inbox notes."""
    result = await db.execute(
        select(func.count(InboxNote.id)).where(
            InboxNote.user_id == user.id,
            InboxNote.status.in_([InboxNoteStatus.pending, InboxNoteStatus.classified]),
        )
    )
    return {"count": result.scalar() or 0}


# ---------------------------------------------------------------------------
# PUT /{id} — Update note
# ---------------------------------------------------------------------------

@router.put("/{note_id}", response_model=InboxNoteResponse)
async def update_inbox_note(
    note_id: int,
    body: InboxNoteUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update an inbox note (text, status, associations)."""
    note = (await db.execute(
        select(InboxNote)
        .where(InboxNote.id == note_id, InboxNote.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if note.status in (InboxNoteStatus.processed, InboxNoteStatus.dismissed):
        raise HTTPException(status_code=409, detail="La nota ya está resuelta")

    update_data = body.model_dump(exclude_unset=True)
    project_id = update_data.get("project_id", note.project_id)
    client_id = update_data.get("client_id", note.client_id)
    await _validate_associations(db, user, project_id, client_id)
    for field, value in update_data.items():
        setattr(note, field, value)
    classification_input_changed = bool(
        {"raw_text", "project_id", "client_id"}.intersection(update_data)
    )
    if "raw_text" in update_data:
        text_value = (update_data["raw_text"] or "").strip()
        if not text_value:
            raise HTTPException(status_code=400, detail="El texto no puede estar vacío")
        note.raw_text = text_value
    if classification_input_changed:
        note.status = (
            InboxNoteStatus.classified
            if note.project_id is not None or note.client_id is not None
            else InboxNoteStatus.pending
        )
        note.ai_suggestion = None
        note.classification_error_code = None
        note.classification_next_attempt_at = None
    note.updated_at = _updated_clock()

    await db.commit()
    await safe_refresh(db, note, log_context="update_inbox_note")
    return _to_response(note, user)


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------

@router.delete("/{note_id}")
async def delete_inbox_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Delete an inbox note."""
    note = (await db.execute(
        select(InboxNote)
        .where(InboxNote.id == note_id, InboxNote.user_id == user.id)
        .with_for_update()
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    await db.delete(note)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /{id}/classify — Trigger AI classification
# ---------------------------------------------------------------------------

@router.post("/{note_id}/classify", response_model=InboxNoteResponse, status_code=202)
async def classify_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Durably enqueue (or re-enqueue) classification without calling AI inline."""
    ai_limiter.check(user.id, max_requests=20, window_seconds=60)
    note = (await db.execute(
        select(InboxNote)
        .where(InboxNote.id == note_id, InboxNote.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if note.status in (InboxNoteStatus.processed, InboxNoteStatus.dismissed):
        raise HTTPException(status_code=409, detail="La nota ya está resuelta")
    note.status = InboxNoteStatus.pending
    note.ai_suggestion = None
    note.classification_error_code = None
    note.classification_next_attempt_at = None
    note.updated_at = _updated_clock()
    await db.commit()
    await safe_refresh(db, note, log_context="inbox_requeue")
    return _to_response(note, user)


# ---------------------------------------------------------------------------
# POST /{id}/convert-to-task — Create task from note
# ---------------------------------------------------------------------------

@router.post("/{note_id}/convert-to-task")
async def convert_to_task(
    note_id: int,
    body: ConvertToTaskBody | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_module("tasks", write=True)),
) -> dict:
    """Convert an inbox note into a real task."""
    note = (await db.execute(
        select(InboxNote)
        .where(InboxNote.id == note_id, InboxNote.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    body = body or ConvertToTaskBody()
    if note.status == InboxNoteStatus.dismissed:
        raise HTTPException(status_code=409, detail="La nota ya fue descartada")

    # A retry (including a concurrent waiter) resolves to the task already
    # created by this same actor instead of creating a duplicate.
    if note.status == InboxNoteStatus.processed:
        if note.resolved_as == "task" and note.resolved_entity_id is not None:
            existing_task = await db.get(Task, note.resolved_entity_id)
            if existing_task is not None and existing_task.created_by == user.id:
                return {"ok": True, "task_id": existing_task.id, "note": _to_response(note, user).model_dump()}
        raise HTTPException(status_code=409, detail="Esta nota ya fue convertida en tarea")

    # Resolve fields: explicit > AI suggestion > defaults
    ai = _visible_suggestion(note, user) or {}

    title = body.title or ai.get("suggested_title") or note.raw_text[:200]
    project_id = body.project_id or (
        note.project_id if _can_read(user, "projects") else None
    )
    client_id = body.client_id or (
        note.client_id if _can_read(user, "clients") else None
    )

    # Infer client from AI suggestion if not set (defend against malformed AI data)
    suggested_client = ai.get("suggested_client")
    if not client_id and isinstance(suggested_client, dict):
        client_id = suggested_client.get("id")
    # Infer project from AI suggestion if not set
    suggested_project = ai.get("suggested_project")
    if not project_id and isinstance(suggested_project, dict):
        project_id = suggested_project.get("id")
    await _validate_associations(db, user, project_id, client_id)
    # Infer client from project
    if project_id and not client_id:
        proj = await db.execute(select(Project.client_id).where(Project.id == project_id))
        row = proj.first()
        if row:
            client_id = row.client_id

    scope = {"client_id": client_id, "project_id": project_id}
    await validate_task_scope(db, scope)
    client_id = scope.get("client_id")
    project_id = scope.get("project_id")

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Se necesita un cliente para crear la tarea. Asigna uno manualmente.",
        )

    priority_str = body.priority or ai.get("suggested_priority", "medium")
    try:
        priority = TaskPriority(priority_str)
    except ValueError:
        priority = TaskPriority.medium

    try:
        # Inbox owns these adapter defaults; the shared writer only enforces
        # domain invariants and attribution.
        task = await create_task_write(db, {
            "title": title,
            "description": note.raw_text,
            "status": TaskStatus.pending,
            "priority": priority,
            "client_id": client_id,
            "project_id": project_id,
            "assigned_to": body.assigned_to or user.id,
            "due_date": body.due_date,
            "scheduled_date": business_today(),
            "link_url": note.link_url,
        }, actor=user)
        note.status = InboxNoteStatus.processed
        note.resolved_as = "task"
        note.resolved_entity_id = task.id
        note.updated_at = _updated_clock()
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.error("DB integrity error converting note %d to task: %s", note_id, e)
        raise HTTPException(
            status_code=400,
            detail="Error al crear la tarea: referencia inválida (cliente, proyecto o usuario inexistente)",
        )

    # Refresh to re-load relationships (project, client) after commit
    try:
        await safe_refresh(db, note, ["project", "client", "attachments"], log_context="inbox")
    except Exception as e:
        logger.debug("Failed to refresh note relationships after convert-to-task (not critical): %s", e)
        pass  # relationships not critical for response

    try:
        note_data = _to_response(note, user).model_dump()
    except Exception as e:
        logger.debug("Failed to serialize note after convert-to-task: %s", e)
        note_data = {"id": note_id, "status": "processed"}

    return {
        "ok": True,
        "task_id": task.id,
        "note": note_data,
    }


# ---------------------------------------------------------------------------
# POST /{id}/dismiss
# ---------------------------------------------------------------------------

@router.post("/{note_id}/dismiss", response_model=InboxNoteResponse)
async def dismiss_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Dismiss an inbox note."""
    note = (await db.execute(
        select(InboxNote)
        .where(InboxNote.id == note_id, InboxNote.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if note.status == InboxNoteStatus.processed:
        raise HTTPException(status_code=409, detail="La nota ya fue convertida en tarea")
    note.status = InboxNoteStatus.dismissed
    note.resolved_as = "dismissed"
    note.updated_at = _updated_clock()
    await db.commit()
    await safe_refresh(db, note, log_context="dismiss_inbox_note")
    return _to_response(note, user)


# ── Attachments ──────────────────────────────────────

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
INLINE_RASTER_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
})
PDF_MIME_TYPE = "application/pdf"


@router.post("/{note_id}/attachments")
async def upload_attachment(
    note_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload an attachment to an inbox note."""
    note = await _get_note_or_404(note_id, user.id, db)

    filename = file.filename or "unnamed"
    mime_type = file.content_type or "application/octet-stream"
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="El nombre del archivo es demasiado largo")
    if len(mime_type) > 100:
        raise HTTPException(status_code=400, detail="El tipo del archivo es demasiado largo")

    content = await file.read(MAX_ATTACHMENT_SIZE + 1)
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="El archivo supera el límite de 10 MB")

    # Prevent duplicate filenames on the same note
    existing = await db.execute(
        select(InboxAttachment).where(
            InboxAttachment.note_id == note_id,
            InboxAttachment.name == filename,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Ya existe un adjunto con el nombre '{filename}'")

    attachment = InboxAttachment(
        note_id=note.id,
        name=filename,
        mime_type=mime_type,
        size_bytes=len(content),
        content=content,
        uploaded_by=user.id,
    )
    db.add(attachment)
    await db.commit()
    await safe_refresh(db, attachment, log_context="upload_inbox_attachment")

    return {
        "id": attachment.id,
        "name": attachment.name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
    }


@router.get("/{note_id}/attachments")
async def list_attachments(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List attachments for an inbox note (without content)."""
    await _get_note_or_404(note_id, user.id, db)
    result = await db.execute(
        select(InboxAttachment).where(InboxAttachment.note_id == note_id)
    )
    attachments = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in attachments
    ]


@router.get("/{note_id}/attachments/{attachment_id}")
async def download_attachment(
    note_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Download/view an attachment inline."""
    await _get_note_or_404(note_id, user.id, db)
    result = await db.execute(
        select(InboxAttachment).where(
            InboxAttachment.id == attachment_id,
            InboxAttachment.note_id == note_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    # Only formats with a known passive browser representation are rendered
    # inline. Existing SVG/HTML and unknown uploads remain downloadable without
    # trusting their stored, client-provided Content-Type.
    inline = attachment.mime_type in INLINE_RASTER_MIME_TYPES or attachment.mime_type == PDF_MIME_TYPE
    disposition = "inline" if inline else "attachment"
    media_type = attachment.mime_type if inline else "application/octet-stream"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(attachment.name, safe='')}",
        "Content-Length": str(attachment.size_bytes),
        "X-Content-Type-Options": "nosniff",
    }
    if attachment.mime_type == PDF_MIME_TYPE:
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"

    return Response(
        content=attachment.content,
        media_type=media_type,
        headers=headers,
    )


@router.delete("/{note_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    note_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete an attachment from an inbox note."""
    await _get_note_or_404(note_id, user.id, db)
    result = await db.execute(
        select(InboxAttachment).where(
            InboxAttachment.id == attachment_id,
            InboxAttachment.note_id == note_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    await db.delete(attachment)
    await db.commit()
