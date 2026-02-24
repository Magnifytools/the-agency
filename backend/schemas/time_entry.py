from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


class TimeEntryCreate(BaseModel):
    minutes: int
    task_id: int
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
    task_id: int
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

    model_config = {"from_attributes": True}
