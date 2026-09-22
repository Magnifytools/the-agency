from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.db.models import TaskPriority, TaskStatus
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
    # Intent-only field for personal capture flows. The route resolves it from
    # the authenticated actor; it is never persisted as task data.
    assign_to_current_user: bool = Field(default=False, exclude=True)
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

    @field_validator("status", mode="before")
    @classmethod
    def status_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("El estado no puede ser nulo")
        return value


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


class CarryoverDecisionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["reschedule", "wait", "complete", "retire"]
    expected_updated_at: datetime
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = Field(None, max_length=255)
    follow_up_date: Optional[date] = None
    reason: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_action_fields(self):
        supplied = {
            "scheduled_date": self.scheduled_date is not None,
            "waiting_for": self.waiting_for is not None,
            "follow_up_date": self.follow_up_date is not None,
            "reason": self.reason is not None,
        }
        allowed = {
            "reschedule": {"scheduled_date"},
            "wait": {"waiting_for", "follow_up_date"},
            "complete": set(),
            "retire": {"reason"},
        }[self.action]
        unexpected = sorted(key for key, present in supplied.items() if present and key not in allowed)
        if unexpected:
            raise ValueError(f"Campos incompatibles con {self.action}: {', '.join(unexpected)}")
        required = allowed - {key for key, present in supplied.items() if present}
        if required:
            raise ValueError(f"Faltan campos para {self.action}: {', '.join(sorted(required))}")
        return self


class TaskRestoreRequest(BaseModel):
    model_config = {"extra": "forbid"}
    expected_updated_at: datetime


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
    project_requires_task_review: bool = False
    project_review_owner_id: Optional[int] = None
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
    retired_at: Optional[datetime] = None
    retired_reason: Optional[str] = None

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

    @field_serializer("retired_at", when_used="json")
    def serialize_retired_at(self, value: datetime | None) -> str | None:
        return utc_isoformat(value)

    @field_serializer("start_date", "due_date", when_used="json")
    def serialize_civil_datetime(self, value: datetime | None) -> str | None:
        return civil_date_isoformat(value)

    model_config = {"from_attributes": True}
