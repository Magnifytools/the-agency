from __future__ import annotations
from typing import Literal, Optional

from datetime import datetime, date
from pydantic import BaseModel, Field, field_serializer
from backend.db.models import TaskStatus, TaskPriority
from backend.services.temporal import civil_date_isoformat, utc_isoformat


class TaskCreate(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.pending
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: Optional[int] = Field(None, ge=0)
    actual_minutes: Optional[int] = Field(None, ge=0)
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    client_id: Optional[int] = None
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = Field(None, max_length=255)
    follow_up_date: Optional[date] = None
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurrence_anchor_date: Optional[date] = None
    unit_cost: Optional[float] = None
    link_url: Optional[str] = None


class TaskUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    estimated_minutes: Optional[int] = Field(None, ge=0)
    actual_minutes: Optional[int] = Field(None, ge=0)
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    client_id: Optional[int] = None
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = Field(None, max_length=255)
    follow_up_date: Optional[date] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurrence_anchor_date: Optional[date] = None
    recurrence_paused: Optional[bool] = None
    unit_cost: Optional[float] = None
    link_url: Optional[str] = None


class RecurrenceSummaryResponse(BaseModel):
    state: Literal["inactive", "active", "paused", "ended", "blocked_client", "blocked_project", "invalid"]
    reason: Optional[str] = None
    label: str
    next_dates: list[date]


class RecurrencePreviewRequest(BaseModel):
    is_recurring: bool = True
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurrence_anchor_date: Optional[date] = None
    recurrence_paused: bool = False
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    client_id: Optional[int] = None
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None
    created_by: Optional[int] = None
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = None
    follow_up_date: Optional[date] = None
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurrence_anchor_date: Optional[date] = None
    recurrence_paused_at: Optional[datetime] = None
    recurrence_summary: RecurrenceSummaryResponse
    recurring_parent_id: Optional[int] = None
    recurrence_occurrence_date: Optional[date] = None
    unit_cost: Optional[float] = None
    invoiced_at: Optional[datetime] = None
    link_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    # Nested names for display
    client_name: Optional[str] = None
    category_name: Optional[str] = None
    assigned_user_name: Optional[str] = None
    project_name: Optional[str] = None
    phase_name: Optional[str] = None
    dependency_title: Optional[str] = None
    created_by_name: Optional[str] = None
    recurring_parent_title: Optional[str] = None
    checklist_count: int = 0

    @field_serializer("completed_at", when_used="json")
    def serialize_completed_at(self, value: datetime | None) -> str | None:
        return utc_isoformat(value)

    @field_serializer("recurrence_paused_at", when_used="json")
    def serialize_recurrence_paused_at(self, value: datetime | None) -> str | None:
        return utc_isoformat(value)

    @field_serializer("start_date", "due_date", when_used="json")
    def serialize_civil_datetime(self, value: datetime | None) -> str | None:
        return civil_date_isoformat(value)

    model_config = {"from_attributes": True}
