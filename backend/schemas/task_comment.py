from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class TaskCommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    # Personas elegidas con @ en el comentario: reciben "te ha mencionado".
    # No se guardan; sólo deciden a quién se avisa.
    mention_ids: list[int] = Field(default_factory=list, max_length=20)


class TaskCommentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    text: str
    user_name: Optional[str] = None
    is_ai_draft: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
