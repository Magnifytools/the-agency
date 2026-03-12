from __future__ import annotations
from typing import Optional

from datetime import datetime, date
from pydantic import BaseModel, Field
from backend.db.models import TaskStatus, TaskPriority


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.pending
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
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = Field(None, max_length=255)
    follow_up_date: Optional[date] = None
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurring_parent_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
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
    scheduled_date: Optional[date] = None
    waiting_for: Optional[str] = Field(None, max_length=255)
    follow_up_date: Optional[date] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_end_date: Optional[date] = None
    recurring_parent_id: Optional[int] = None


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
    recurring_parent_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

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

    model_config = {"from_attributes": True}
