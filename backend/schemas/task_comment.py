from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class TaskCommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class TaskCommentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    text: str
    user_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
