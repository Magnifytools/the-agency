from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


class TimeEntryCreate(BaseModel):
    minutes: int
    task_id: Optional[int] = None
    notes: Optional[str] = None
    date: Optional[datetime] = None


class TimeEntryUpdate(BaseModel):
    minutes: Optional[int] = None
    notes: Optional[str] = None
    task_id: Optional[int] = None


class TimeEntryResponse(BaseModel):
    id: int
    minutes: Optional[int] = None
    started_at: Optional[datetime] = None
    date: datetime
    notes: Optional[str] = None
    task_id: Optional[int] = None
    user_id: int
    created_at: datetime
    updated_at: datetime

    # Denormalized
    task_title: Optional[str] = None
    client_name: Optional[str] = None

    model_config = {"from_attributes": True}


class TimerStartRequest(BaseModel):
    task_id: Optional[int] = None
    notes: Optional[str] = None


class TimerStopRequest(BaseModel):
    notes: Optional[str] = None


class ActiveTimerResponse(BaseModel):
    id: int
    task_id: Optional[int] = None
    task_title: Optional[str] = None
    client_name: Optional[str] = None
    started_at: datetime
    is_paused: bool = False
    accumulated_seconds: int = 0

    model_config = {"from_attributes": True}


class AdminActiveTimerResponse(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_email: str
    task_id: Optional[int] = None
    task_title: Optional[str] = None
    client_name: Optional[str] = None
    started_at: datetime
    elapsed_seconds: int

    model_config = {"from_attributes": True}


class ProjectTeamBreakdown(BaseModel):
    user_id: int
    user_name: str
    total_minutes: int
    entries_count: int


class ProjectTimeReport(BaseModel):
    project_id: int
    project_name: str
    client_id: int
    client_name: str
    total_minutes: int
    entries_count: int
    team_breakdown: list[ProjectTeamBreakdown]


class ClientTeamBreakdown(BaseModel):
    user_id: int
    user_name: str
    total_minutes: int
    cost_eur: float


class ClientTimeReport(BaseModel):
    client_id: Optional[int]
    client_name: str
    total_minutes: int
    entries_count: int
    cost_eur: float
    team_breakdown: list[ClientTeamBreakdown]
