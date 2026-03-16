from __future__ import annotations
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, Field


class DayStatusUpdate(BaseModel):
    date: date
    status: str = "available"
    label: Optional[str] = Field(None, max_length=100)
    note: Optional[str] = None


class DayStatusResponse(BaseModel):
    id: int
    user_id: int
    date: date
    status: str
    label: Optional[str] = None
    note: Optional[str] = None

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    date: date
    time: Optional[str] = Field(None, max_length=5)
    title: str = Field(..., max_length=200)
    client_id: Optional[int] = None
    event_type: str = "meeting"
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    is_all_day: bool = False


class EventUpdate(BaseModel):
    date: Optional[date] = None
    time: Optional[str] = Field(None, max_length=5)
    title: Optional[str] = Field(None, max_length=200)
    client_id: Optional[int] = None
    event_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    is_all_day: Optional[bool] = None


class EventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    event_type: str
    date: date
    time: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_all_day: bool = False
    duration_minutes: Optional[int] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    user_id: int

    model_config = {"from_attributes": True}


class CompanyHolidayCreate(BaseModel):
    date: date
    name: str = Field(..., max_length=100)
    country: str = Field("ES", max_length=5)
    region: Optional[str] = Field(None, max_length=10)
    locality: Optional[str] = Field(None, max_length=100)


class CompanyHolidayResponse(BaseModel):
    id: int
    date: date
    name: str
    country: str
    region: Optional[str] = None
    locality: Optional[str] = None

    model_config = {"from_attributes": True}


class MyWeekTask(BaseModel):
    id: int
    title: str
    status: str
    priority: str
    scheduled_date: Optional[date] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    created_at: datetime
    last_comment: Optional[str] = None
    last_comment_at: Optional[datetime] = None
    checklist_total: int = 0
    checklist_done: int = 0
    weeks_open: int = 0

    model_config = {"from_attributes": True}


class MyWeekDay(BaseModel):
    date: date
    weekday: str
    status: Optional[DayStatusResponse] = None
    is_holiday: Optional[CompanyHolidayResponse] = None
    events: list[EventResponse] = []
    tasks: list[MyWeekTask] = []


class MyWeekSummary(BaseModel):
    total_tasks: int = 0
    estimated_minutes: int = 0
    available_hours: float = 0
    tasks_dragging: int = 0
    tasks_no_estimate: int = 0
    tasks_no_date: int = 0
    by_client: list[dict] = []


class MyWeekResponse(BaseModel):
    week_start: date
    week_end: date
    days: list[MyWeekDay] = []
    backlog: list[MyWeekTask] = []
    summary: MyWeekSummary = MyWeekSummary()
