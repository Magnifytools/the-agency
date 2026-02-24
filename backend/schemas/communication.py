from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


class CommunicationCreate(BaseModel):
    channel: str  # email, call, meeting, whatsapp, slack, other
    direction: str  # inbound, outbound
    subject: Optional[str] = None
    summary: str
    contact_name: Optional[str] = None
    occurred_at: datetime
    requires_followup: bool = False
    followup_date: Optional[datetime] = None
    followup_notes: Optional[str] = None


class CommunicationUpdate(BaseModel):
    channel: Optional[str] = None
    direction: Optional[str] = None
    subject: Optional[str] = None
    summary: Optional[str] = None
    contact_name: Optional[str] = None
    occurred_at: Optional[datetime] = None
    requires_followup: Optional[bool] = None
    followup_date: Optional[datetime] = None
    followup_notes: Optional[str] = None


class CommunicationResponse(BaseModel):
    id: int
    channel: str
    direction: str
    subject: Optional[str]
    summary: str
    contact_name: Optional[str]
    occurred_at: datetime
    requires_followup: bool
    followup_date: Optional[datetime]
    followup_notes: Optional[str]
    client_id: int
    user_id: int
    user_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
