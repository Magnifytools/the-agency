from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
import logging

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, noload, selectinload

logger = logging.getLogger(__name__)

from backend.db.database import get_db
from backend.db.models import User, Project, ProjectEvidence, EvidenceType
from backend.schemas.evidence import EvidenceCreate, EvidenceUpdate, EvidenceResponse
from backend.api.deps import require_module
from backend.api.utils.db_helpers import reload_for_response
from backend.api.middleware.audit_log import log_audit

router = APIRouter(prefix="/api/projects/{project_id}/evidence", tags=["evidence"])

_ALLOWED_EVIDENCE_MIME_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
    "application/zip",
}
_ALLOWED_EVIDENCE_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".doc", ".docx", ".xls", ".xlsx",
    ".txt", ".csv", ".zip",
}
_MAX_EVIDENCE_BYTES = 20 * 1024 * 1024


def _to_response(project_id: int, ev: ProjectEvidence) -> dict:
    data = {
        "id": ev.id,
        "project_id": ev.project_id,
        "phase_id": ev.phase_id,
        "title": ev.title,
        "url": ev.url,
        "evidence_type": ev.evidence_type,
        "description": ev.description,
        "created_by": ev.created_by,
        "created_at": ev.created_at,
        "updated_at": ev.updated_at,
        "file_name": ev.file_name,
        "file_mime_type": ev.file_mime_type,
        "file_size_bytes": ev.file_size_bytes,
    }
    try:
        data["creator_name"] = ev.creator.full_name if ev.creator else None
    except Exception:
        data["creator_name"] = None
    try:
        data["phase_name"] = ev.phase.name if ev.phase else None
    except Exception:
        data["phase_name"] = None
    data["has_file"] = bool(ev.file_name)
    data["download_url"] = (
        f"/api/projects/{project_id}/evidence/{ev.id}/download"
        if data["has_file"]
        else None
    )
    data["preview_url"] = (
        f"/api/projects/{project_id}/evidence/{ev.id}/preview"
        if data["has_file"]
        else None
    )
    return data


async def _ensure_project_exists(db: AsyncSession, project_id: int) -> None:
    proj = await db.execute(select(Project).where(Project.id == project_id))
    if proj.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _validate_upload(file: UploadFile, content: bytes) -> None:
    filename = file.filename or ""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _ALLOWED_EVIDENCE_EXTENSIONS:
        raise HTTPException(400, f"Extensión no permitida: {ext or '(sin extensión)'}")
    if not file.content_type or file.content_type not in _ALLOWED_EVIDENCE_MIME_TYPES:
        raise HTTPException(400, f"Tipo de archivo no permitido: {file.content_type or '(sin tipo)'}")
    if len(content) > _MAX_EVIDENCE_BYTES:
        raise HTTPException(400, "Archivo demasiado grande (máx 20 MB)")


_EVIDENCE_RELOAD_OPTIONS = [
    defer(ProjectEvidence.file_content),
    selectinload(ProjectEvidence.creator),
    selectinload(ProjectEvidence.phase),
]


async def _reload_evidence(db: AsyncSession, evidence_id: int) -> ProjectEvidence:
    """Reload evidence by ID with eager-loaded relationships (safe after commit)."""
    ev = await reload_for_response(
        db, ProjectEvidence, evidence_id, options=_EVIDENCE_RELOAD_OPTIONS,
    )
    if ev is None:
        raise HTTPException(status_code=500, detail="Error recargando evidencia")
    return ev


def _safe_filename(name: str) -> str:
    return name.replace('"', "_").replace("\n", "_").replace("\r", "_")


@router.get("", response_model=list[EvidenceResponse])
async def list_evidence(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects")),
):
    try:
        result = await db.execute(
            select(ProjectEvidence)
            .options(
                defer(ProjectEvidence.file_content),
                selectinload(ProjectEvidence.creator),
                selectinload(ProjectEvidence.phase).options(noload("*")),
            )
            .where(ProjectEvidence.project_id == project_id)
            .order_by(ProjectEvidence.created_at.desc())
        )
        return [_to_response(project_id, ev) for ev in result.scalars().all()]
    except Exception as e:
        logger.error("Error listing evidence for project %s: %s", project_id, e)
        raise HTTPException(status_code=500, detail="Error al listar evidencias")


@router.post("", response_model=EvidenceResponse, status_code=201)
async def create_evidence(
    project_id: int,
    body: EvidenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("projects", write=True)),
):
    await _ensure_project_exists(db, project_id)
    if not body.url:
        raise HTTPException(status_code=400, detail="Añade una URL o sube un archivo")

    evidence = ProjectEvidence(
        project_id=project_id,
        created_by=current_user.id,
        **body.model_dump(),
    )
    db.add(evidence)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Referencia inválida (fase o proyecto inexistente)")
    except DataError as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail="Datos inválidos: campo excede longitud máxima")
    except Exception as e:
        await db.rollback()
        logger.error("Error creating evidence: %s", e)
        raise HTTPException(status_code=500, detail="Error al crear la evidencia")
    try:
        evidence = await _reload_evidence(db, evidence.id)
    except Exception:
        logger.warning("Non-critical: evidence reload failed after creation")
        pass  # evidence object already has the data from creation
    log_audit(current_user.id, "create", "evidence", evidence.id, details=f"project_id={project_id}")
    return _to_response(project_id, evidence)


@router.post("/upload", response_model=EvidenceResponse, status_code=201)
async def upload_evidence(
    project_id: int,
    title: str = Form(...),
    evidence_type: EvidenceType = Form(EvidenceType.other),
    phase_id: int | None = Form(None),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("projects", write=True)),
):
    await _ensure_project_exists(db, project_id)
    content = await file.read()
    _validate_upload(file, content)

    evidence = ProjectEvidence(
        project_id=project_id,
        phase_id=phase_id,
        title=title.strip(),
        evidence_type=evidence_type,
        description=description.strip() if description else None,
        created_by=current_user.id,
        file_name=file.filename or "archivo",
        file_mime_type=file.content_type or "application/octet-stream",
        file_size_bytes=len(content),
        file_content=content,
        url=None,
    )
    db.add(evidence)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Referencia inválida (fase o proyecto inexistente)")
    except DataError as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail="Datos inválidos: campo excede longitud máxima")
    except Exception as e:
        await db.rollback()
        logger.error("Error uploading evidence: %s", e)
        raise HTTPException(status_code=500, detail="Error al subir la evidencia")
    try:
        evidence = await _reload_evidence(db, evidence.id)
    except Exception:
        logger.warning("Non-critical: evidence reload failed after upload")
        pass  # evidence object already has the data from creation
    return _to_response(project_id, evidence)


@router.put("/{evidence_id}", response_model=EvidenceResponse)
async def update_evidence(
    project_id: int,
    evidence_id: int,
    body: EvidenceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects", write=True)),
):
    result = await db.execute(
        select(ProjectEvidence).where(
            ProjectEvidence.id == evidence_id,
            ProjectEvidence.project_id == project_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    _UPDATABLE_EVIDENCE_FIELDS = {"title", "url", "evidence_type", "phase_id", "description"}
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in _UPDATABLE_EVIDENCE_FIELDS:
            setattr(evidence, field, value)
    await db.commit()
    evidence = await _reload_evidence(db, evidence_id)
    return _to_response(project_id, evidence)


@router.get("/{evidence_id}/download")
async def download_evidence(
    project_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects")),
):
    result = await db.execute(
        select(ProjectEvidence).where(
            ProjectEvidence.id == evidence_id,
            ProjectEvidence.project_id == project_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None or not evidence.file_content or not evidence.file_name:
        raise HTTPException(status_code=404, detail="Evidence file not found")
    safe_name = _safe_filename(evidence.file_name)
    return Response(
        content=evidence.file_content,
        media_type=evidence.file_mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.get("/{evidence_id}/preview")
async def preview_evidence(
    project_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects")),
):
    result = await db.execute(
        select(ProjectEvidence).where(
            ProjectEvidence.id == evidence_id,
            ProjectEvidence.project_id == project_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None or not evidence.file_content or not evidence.file_name:
        raise HTTPException(status_code=404, detail="Evidence file not found")
    safe_name = _safe_filename(evidence.file_name)
    return Response(
        content=evidence.file_content,
        media_type=evidence.file_mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.delete("/{evidence_id}", status_code=204)
async def delete_evidence(
    project_id: int,
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects", write=True)),
):
    result = await db.execute(
        select(ProjectEvidence).where(
            ProjectEvidence.id == evidence_id,
            ProjectEvidence.project_id == project_id,
        )
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    await db.delete(evidence)
    await db.commit()
    log_audit(_.id if hasattr(_, "id") else "-", "delete", "evidence", evidence_id, details=f"project_id={project_id}")
