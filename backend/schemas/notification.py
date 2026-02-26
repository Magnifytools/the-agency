from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    type: str
    title: str
    message: Optional[str] = None
    is_read: bool
    link_url: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationCreate(BaseModel):
    user_id: int
    type: str
    title: str
    message: Optional[str] = None
    link_url: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
