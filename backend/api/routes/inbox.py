"""Inbox quick-capture API endpoints."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db, async_session
from backend.db.models import (
    InboxNote, InboxNoteStatus, InboxAttachment, Project, ProjectStatus, Client, ClientStatus,
    Task, TaskStatus, TaskPriority,
)
from backend.api.deps import get_current_user
from backend.api.utils.db_helpers import safe_refresh
from backend.schemas.inbox import (
    InboxNoteCreate, InboxNoteUpdate, InboxNoteResponse, ConvertToTaskBody,
)
from backend.core.rate_limiter import ai_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])

# Keep references to background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


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


def _to_response(note: InboxNote) -> InboxNoteResponse:
    """Convert ORM model to response, populating relationship names."""
    return InboxNoteResponse(
        id=note.id,
        user_id=note.user_id,
        raw_text=note.raw_text,
        source=note.source,
        status=note.status,
        project_id=note.project_id,
        client_id=note.client_id,
        project_name=_safe_rel_name(note, "project"),
        client_name=_safe_rel_name(note, "client"),
        resolved_as=note.resolved_as,
        resolved_entity_id=note.resolved_entity_id,
        ai_suggestion=note.ai_suggestion,
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


async def _fetch_context(db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Fetch active projects and clients for AI classification context."""
    proj_coro = db.execute(
        select(Project.id, Project.name, Client.name.label("client_name"))
        .join(Client, Project.client_id == Client.id)
        .where(Project.status == ProjectStatus.active)
        .order_by(Project.name)
        .limit(200)
    )
    cli_coro = db.execute(
        select(Client.id, Client.name)
        .where(Client.status == ClientStatus.active)
        .order_by(Client.name)
        .limit(200)
    )
    proj_result, cli_result = await asyncio.gather(proj_coro, cli_coro)
    projects = [{"id": r.id, "name": r.name, "client_name": r.client_name} for r in proj_result.all()]
    clients = [{"id": r.id, "name": r.name} for r in cli_result.all()]
    return projects, clients


async def _classify_note_background(note_id: int) -> None:
    """Run AI classification in background (fire-and-forget)."""
    from backend.services.inbox_classifier import classify_inbox_note

    try:
        async with async_session() as db:
            result = await db.execute(select(InboxNote).where(InboxNote.id == note_id))
            note = result.scalar_one_or_none()
            if not note or note.status != InboxNoteStatus.pending:
                return

            projects, clients = await _fetch_context(db)
            if not projects and not clients:
                logger.info("No active projects/clients for classification, skipping note %d", note_id)
                return

            suggestion = await classify_inbox_note(note.raw_text, projects, clients)
            note.ai_suggestion = suggestion
            note.status = InboxNoteStatus.classified
            await db.commit()
            logger.info("Classified inbox note %d -> %s", note_id, suggestion.get("suggested_action"))
    except Exception as e:
        logger.error("Background classification failed for note %d: %s", note_id, e)


# ---------------------------------------------------------------------------
# POST / — Create note
# ---------------------------------------------------------------------------

@router.post("", response_model=InboxNoteResponse, status_code=201)
async def create_inbox_note(
    body: InboxNoteCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Capture a quick note. AI classification fires in background."""
    text = body.raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El texto no puede estar vacio")

    # If user already assigned project/client, skip AI classification
    already_assigned = body.project_id is not None or body.client_id is not None
    initial_status = InboxNoteStatus.classified if already_assigned else InboxNoteStatus.pending

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

    # Only run AI classification if user didn't pre-assign
    if not already_assigned:
        _fire_and_forget(_classify_note_background(note.id))

    return _to_response(note)


# ---------------------------------------------------------------------------
# GET / — List notes
# ---------------------------------------------------------------------------

@router.get("")
async def list_inbox_notes(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
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

    q = q.order_by(InboxNote.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return [_to_response(n) for n in result.scalars().all()]


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
    note = await _get_note_or_404(note_id, user.id, db)

    _UPDATABLE_NOTE_FIELDS = {
        "raw_text", "status", "project_id", "client_id",
        "resolved_as", "resolved_entity_id", "link_url",
    }
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in _UPDATABLE_NOTE_FIELDS:
            setattr(note, field, value)

    await db.commit()
    await safe_refresh(db, note, log_context="update_inbox_note")
    return _to_response(note)


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
    note = await _get_note_or_404(note_id, user.id, db)
    await db.delete(note)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /{id}/classify — Trigger AI classification
# ---------------------------------------------------------------------------

@router.post("/{note_id}/classify", response_model=InboxNoteResponse)
async def classify_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Run (or re-run) AI classification on a note."""
    from backend.services.inbox_classifier import classify_inbox_note

    ai_limiter.check(user.id, max_requests=20, window_seconds=60)

    note = await _get_note_or_404(note_id, user.id, db)
    projects, clients = await _fetch_context(db)

    try:
        suggestion = await classify_inbox_note(note.raw_text, projects, clients)
        note.ai_suggestion = suggestion
        note.status = InboxNoteStatus.classified
        await db.commit()
        await safe_refresh(db, note, log_context="inbox")
    except Exception as e:
        logger.error("Classification failed for note %d: %s", note_id, e)
        raise HTTPException(status_code=502, detail="Error al clasificar con IA")

    return _to_response(note)


# ---------------------------------------------------------------------------
# POST /{id}/convert-to-task — Create task from note
# ---------------------------------------------------------------------------

@router.post("/{note_id}/convert-to-task")
async def convert_to_task(
    note_id: int,
    body: ConvertToTaskBody | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Convert an inbox note into a real task."""
    note = await _get_note_or_404(note_id, user.id, db)
    body = body or ConvertToTaskBody()

    # Guard: don't convert an already-processed note
    if note.status == InboxNoteStatus.processed:
        raise HTTPException(status_code=409, detail="Esta nota ya fue convertida en tarea")

    # Resolve fields: explicit > AI suggestion > defaults
    ai = note.ai_suggestion or {}

    title = body.title or ai.get("suggested_title") or note.raw_text[:200]
    project_id = body.project_id or note.project_id
    client_id = body.client_id or note.client_id

    # Infer client from AI suggestion if not set (defend against malformed AI data)
    suggested_client = ai.get("suggested_client")
    if not client_id and isinstance(suggested_client, dict):
        client_id = suggested_client.get("id")
    # Infer project from AI suggestion if not set
    suggested_project = ai.get("suggested_project")
    if not project_id and isinstance(suggested_project, dict):
        project_id = suggested_project.get("id")
    # Infer client from project
    if project_id and not client_id:
        proj = await db.execute(select(Project.client_id).where(Project.id == project_id))
        row = proj.first()
        if row:
            client_id = row.client_id

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

    from datetime import date as _date
    today = _date.today()
    task = Task(
        title=title,
        description=note.raw_text,
        status=TaskStatus.pending,
        priority=priority,
        client_id=client_id,
        project_id=project_id,
        assigned_to=body.assigned_to or user.id,
        due_date=body.due_date,
        scheduled_date=today,
    )
    db.add(task)

    note.status = InboxNoteStatus.processed
    note.resolved_as = "task"

    try:
        await db.flush()
        note.resolved_entity_id = task.id
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
        note_data = _to_response(note).model_dump()
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
    note = await _get_note_or_404(note_id, user.id, db)
    note.status = InboxNoteStatus.dismissed
    note.resolved_as = "dismissed"
    await db.commit()
    await safe_refresh(db, note, log_context="dismiss_inbox_note")
    return _to_response(note)


# ── Attachments ──────────────────────────────────────

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_PREFIXES = ("image/", "application/pdf", "text/", "application/vnd.", "application/msword")


@router.post("/{note_id}/attachments")
async def upload_attachment(
    note_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Upload an attachment to an inbox note."""
    note = await _get_note_or_404(note_id, user.id, db)

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="El archivo supera el límite de 10 MB")

    # Prevent duplicate filenames on the same note
    existing = await db.execute(
        select(InboxAttachment).where(
            InboxAttachment.note_id == note_id,
            InboxAttachment.name == file.filename,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Ya existe un adjunto con el nombre '{file.filename}'")

    attachment = InboxAttachment(
        note_id=note.id,
        name=file.filename or "unnamed",
        mime_type=file.content_type or "application/octet-stream",
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

    # Serve inline for images/PDFs, attachment for others
    disposition = "inline" if attachment.mime_type.startswith("image/") or attachment.mime_type == "application/pdf" else "attachment"

    return Response(
        content=attachment.content,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{attachment.name}"',
            "Content-Length": str(attachment.size_bytes),
        },
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
