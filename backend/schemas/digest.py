from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_serializer, model_validator

from backend.db.models import DigestStatus, DigestTone


def _serialize_utc(dt: Optional[datetime]) -> Optional[str]:
    """Serialize naive UTC datetime as ISO with 'Z' so clients parse it as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Items within sections ---

class DigestItem(BaseModel):
    title: str
    description: str


class DigestSections(BaseModel):
    done: list[DigestItem] = []
    need: list[DigestItem] = []
    next: list[DigestItem] = []
    metrics: list[DigestItem] = []


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

    @model_validator(mode="after")
    def validate_period(self):
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Debes indicar period_start y period_end juntos")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end no puede ser anterior a period_start")
        return self


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

    @field_serializer("generated_at", "edited_at", "created_at", "updated_at")
    def _ser_dt(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc(dt)

    model_config = {"from_attributes": True}


class DigestRenderResponse(BaseModel):
    format: str  # "slack" | "email"
    rendered: str  # The rendered content (text for Slack, HTML for email)
