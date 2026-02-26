from __future__ import annotations

from typing import Optional
from datetime import date, datetime

from pydantic import BaseModel

from backend.db.models import DailyUpdateStatus


# --- Parsed data structure ---

class ParsedTask(BaseModel):
    description: str
    details: str = ""


class ParsedProject(BaseModel):
    name: str
    client: str = ""
    tasks: list[ParsedTask] = []


class ParsedDailyData(BaseModel):
    projects: list[ParsedProject] = []
    general: list[ParsedTask] = []  # tasks not tied to any project
    tomorrow: list[str] = []  # planned items for next day


# --- API schemas ---

class DailySubmitRequest(BaseModel):
    raw_text: str
    date: Optional[date] = None  # defaults to today


class DailyUpdateResponse(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    date: date
    raw_text: str
    parsed_data: Optional[ParsedDailyData] = None
    status: DailyUpdateStatus
    discord_sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyDiscordResponse(BaseModel):
    success: bool
    message: str
