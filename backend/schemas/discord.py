"""Discord settings and action schemas."""
from __future__ import annotations
from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class DiscordSettingsResponse(BaseModel):
    id: int
    webhook_url: Optional[str] = None
    webhook_configured: bool = False
    auto_daily_summary: bool = False
    summary_time: str = "18:00"
    include_ai_note: bool = True
    last_sent_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DiscordSettingsUpdate(BaseModel):
    webhook_url: Optional[str] = None
    auto_daily_summary: Optional[bool] = None
    summary_time: Optional[str] = None
    include_ai_note: Optional[bool] = None


class DiscordTestResponse(BaseModel):
    success: bool
    message: str


class DiscordSendResponse(BaseModel):
    success: bool
    message: str
    date: Optional[str] = None
