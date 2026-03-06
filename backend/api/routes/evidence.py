from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, Project, ProjectEvidence
from backend.schemas.evidence import EvidenceCreate, EvidenceUpdate, EvidenceResponse
from backend.api.deps import get_current_user, require_module

router = APIRouter(prefix="/api/projects/{project_id}/evidence", tags=["evidence"])


def _to_response(ev: ProjectEvidence) -> dict:
    data = {c.name: getattr(ev, c.name) for c in ev.__table__.columns}
    data["creator_name"] = ev.creator.full_name if ev.creator else None
    data["phase_name"] = ev.phase.name if ev.phase else None
    return data


@router.get("", response_model=list[EvidenceResponse])
async def list_evidence(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("projects")),
):
    result = await db.execute(
        select(ProjectEvidence)
        .where(ProjectEvidence.project_id == project_id)
        .order_by(ProjectEvidence.created_at.desc())
    )
    return [_to_response(ev) for ev in result.scalars().all()]


@router.post("", response_model=EvidenceResponse, status_code=201)
async def create_evidence(
    project_id: int,
    body: EvidenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("projects", write=True)),
):
    proj = await db.execute(select(Project).where(Project.id == project_id))
    if proj.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    evidence = ProjectEvidence(
        project_id=project_id,
        created_by=current_user.id,
        **body.model_dump(),
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return _to_response(evidence)


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
    await db.refresh(evidence)
    return _to_response(evidence)


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
