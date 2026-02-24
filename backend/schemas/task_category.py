from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


class TaskCategoryCreate(BaseModel):
    name: str
    default_minutes: int = 60


class TaskCategoryUpdate(BaseModel):
    name: Optional[str] = None
    default_minutes: Optional[int] = None


class TaskCategoryResponse(BaseModel):
    id: int
    name: str
    default_minutes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
