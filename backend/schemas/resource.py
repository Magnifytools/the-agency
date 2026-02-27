from __future__ import annotations

from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from backend.db.models import ResourceType


class ResourceCreate(BaseModel):
    label: str
    url: str
    resource_type: ResourceType = ResourceType.other
    notes: Optional[str] = None


class ResourceUpdate(BaseModel):
    label: Optional[str] = None
    url: Optional[str] = None
    resource_type: Optional[ResourceType] = None
    notes: Optional[str] = None


class ResourceResponse(BaseModel):
    id: int
    client_id: int
    label: str
    url: str
    resource_type: ResourceType
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
