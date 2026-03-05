"""Inbox note schemas for quick capture system."""
from __future__ import annotations
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel

from backend.db.models import InboxNoteStatus


class InboxNoteCreate(BaseModel):
    raw_text: str
    source: str = "dashboard"
    project_id: Optional[int] = None
    client_id: Optional[int] = None


class InboxNoteUpdate(BaseModel):
    raw_text: Optional[str] = None
    status: Optional[InboxNoteStatus] = None
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    resolved_as: Optional[str] = None
    resolved_entity_id: Optional[int] = None


class ConvertToTaskBody(BaseModel):
    title: Optional[str] = None
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None


class InboxNoteResponse(BaseModel):
    id: int
    user_id: int
    raw_text: str
    source: str
    status: InboxNoteStatus
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    project_name: Optional[str] = None
    client_name: Optional[str] = None
    resolved_as: Optional[str] = None
    resolved_entity_id: Optional[int] = None
    ai_suggestion: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
