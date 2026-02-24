from __future__ import annotations
from typing import Optional

from pydantic import BaseModel


class AlertSettingsUpdate(BaseModel):
    days_without_activity: Optional[int] = None
    days_before_deadline: Optional[int] = None
    days_without_contact: Optional[int] = None
    max_tasks_per_week: Optional[int] = None
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None


class AlertSettingsResponse(BaseModel):
    id: int
    user_id: int
    days_without_activity: int
    days_before_deadline: int
    days_without_contact: int
    max_tasks_per_week: int
    notify_in_app: bool
    notify_email: bool

    class Config:
        from_attributes = True
