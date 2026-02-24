from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

from backend.db.models import ProposalStatus

class ProposalBase(BaseModel):
    title: str = Field(..., max_length=200)
    status: ProposalStatus = ProposalStatus.draft
    budget: Optional[float] = None
    scope: Optional[str] = None
    valid_until: Optional[datetime] = None
    client_id: int
    project_id: Optional[int] = None

class ProposalCreate(ProposalBase):
    pass

class ProposalUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    status: Optional[ProposalStatus] = None
    budget: Optional[float] = None
    scope: Optional[str] = None
    valid_until: Optional[datetime] = None
    client_id: Optional[int] = None
    project_id: Optional[int] = None

class ProposalResponse(ProposalBase):
    id: int
    created_at: datetime
    updated_at: datetime
    client_name: Optional[str] = None
    project_name: Optional[str] = None

    class Config:
        from_attributes = True
