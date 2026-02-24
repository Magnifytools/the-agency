from __future__ import annotations
from typing import Optional
from datetime import date, datetime

from pydantic import BaseModel

from backend.db.models import DigestStatus, DigestTone


# --- Items within sections ---

class DigestItem(BaseModel):
    title: str
    description: str


class DigestSections(BaseModel):
    done: list[DigestItem] = []
    need: list[DigestItem] = []
    next: list[DigestItem] = []


class DigestContent(BaseModel):
    greeting: str = ""
    date: str = ""
    sections: DigestSections = DigestSections()
    closing: str = ""


# --- API schemas ---

class DigestGenerateRequest(BaseModel):
    client_id: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    tone: DigestTone = DigestTone.cercano


class DigestUpdateRequest(BaseModel):
    content: Optional[DigestContent] = None
    tone: Optional[DigestTone] = None


class DigestStatusUpdate(BaseModel):
    status: DigestStatus


class DigestResponse(BaseModel):
    id: int
    client_id: int
    client_name: Optional[str] = None
    period_start: date
    period_end: date
    status: DigestStatus
    tone: DigestTone
    content: Optional[DigestContent] = None
    raw_context: Optional[dict] = None
    generated_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    created_by: int
    creator_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DigestRenderResponse(BaseModel):
    format: str  # "slack" | "email"
    rendered: str  # The rendered content (text for Slack, HTML for email)
