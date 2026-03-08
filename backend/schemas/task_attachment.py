from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class TaskAttachmentResponse(BaseModel):
    id: int
    task_id: int
    name: str
    description: Optional[str] = None
    mime_type: str
    size_bytes: int
    uploaded_by: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
