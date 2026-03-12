from __future__ import annotations

from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from backend.db.models import EvidenceType


class EvidenceCreate(BaseModel):
    title: str
    url: Optional[str] = None
    evidence_type: EvidenceType = EvidenceType.other
    phase_id: Optional[int] = None
    description: Optional[str] = None


class EvidenceUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    evidence_type: Optional[EvidenceType] = None
    phase_id: Optional[int] = None
    description: Optional[str] = None


class EvidenceResponse(BaseModel):
    id: int
    project_id: int
    phase_id: Optional[int] = None
    title: str
    url: Optional[str] = None
    evidence_type: EvidenceType
    description: Optional[str] = None
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    phase_name: Optional[str] = None
    has_file: bool = False
    file_name: Optional[str] = None
    file_mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    download_url: Optional[str] = None
    preview_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
