from __future__ import annotations

from typing import Optional
from datetime import date as date_type, datetime

from pydantic import BaseModel, Field

from backend.db.models import DailyUpdateStatus


# --- Parsed data structure ---

class ParsedTask(BaseModel):
    description: str
    details: str = ""
    fact_keys: list[str] = Field(default_factory=list)


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
    raw_text: str = Field(max_length=50000)
    date: Optional[date_type] = None  # defaults to today
    source_fact_keys: list[str] = Field(default_factory=list, max_length=500)


class DailyEditRequest(BaseModel):
    revision: int = Field(ge=1)
    raw_text: Optional[str] = Field(default=None, max_length=50000)
    parsed_data: Optional[ParsedDailyData] = None
    source_fact_keys: Optional[list[str]] = Field(default=None, max_length=500)


class DailyEnrichRequest(BaseModel):
    revision: int = Field(ge=1)


class DailyUpdateResponse(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    date: date_type
    raw_text: str
    parsed_data: Optional[ParsedDailyData] = None
    status: DailyUpdateStatus
    discord_sent_at: Optional[datetime] = None
    time_entries_created: int = 0
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    source_facts: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DailyDiscordResponse(BaseModel):
    success: bool
    message: str
