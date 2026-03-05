from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class ChecklistItemCreate(BaseModel):
    text: str
    order_index: int = 0


class ChecklistItemUpdate(BaseModel):
    text: Optional[str] = None
    is_done: Optional[bool] = None
    order_index: Optional[int] = None


class ChecklistItemResponse(BaseModel):
    id: int
    task_id: int
    text: str
    is_done: bool
    order_index: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
