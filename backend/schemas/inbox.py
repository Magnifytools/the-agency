"""Inbox note schemas for quick capture system."""
from __future__ import annotations
from typing import Literal, Optional
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

from backend.db.models import InboxNoteStatus


class InboxNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(max_length=10_000)
    source: Literal["dashboard", "quick_capture", "chrome_extension"] = "dashboard"
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    link_url: Optional[str] = None


class InboxNoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: Optional[str] = Field(default=None, max_length=10_000)
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    link_url: Optional[str] = None


class ConvertToTaskBody(BaseModel):
    title: Optional[str] = None
    project_id: Optional[int] = None
    client_id: Optional[int] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    due_date: Optional[date] = None  # defaults to today if not set


class AttachmentInfo(BaseModel):
    id: int
    name: str
    mime_type: str
    size_bytes: int

    model_config = {"from_attributes": True}


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
    classification_error_code: Optional[str] = None
    classification_next_attempt_at: Optional[datetime] = None
    link_url: Optional[str] = None
    attachments: list[AttachmentInfo] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
