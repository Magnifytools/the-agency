from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel
from backend.db.models import TaskStatus, TaskPriority


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.pending
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    client_id: int
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    estimated_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    client_id: Optional[int] = None
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    client_id: int
    category_id: Optional[int] = None
    assigned_to: Optional[int] = None
    project_id: Optional[int] = None
    phase_id: Optional[int] = None
    depends_on: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Nested names for display
    client_name: Optional[str] = None
    category_name: Optional[str] = None
    assigned_user_name: Optional[str] = None
    project_name: Optional[str] = None
    phase_name: Optional[str] = None

    model_config = {"from_attributes": True}
