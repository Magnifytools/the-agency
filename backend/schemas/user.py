from __future__ import annotations
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field
from backend.db.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.member
    hourly_rate: Optional[float] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    hourly_rate: Optional[float] = None
    cost_per_hour: Optional[float] = None
    available_hours_month: Optional[float] = None
    role: Optional[UserRole] = None
    preferences: Optional[dict[str, Any]] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    short_name: Optional[str] = None
    birthday: Optional[str | date] = None  # ISO date string or date object
    job_title: Optional[str] = None
    morning_reminder_time: Optional[str] = None
    evening_reminder_time: Optional[str] = None
    onboarding_completed: Optional[bool] = None


class UserListResponse(BaseModel):
    id: int
    email: Optional[str] = None
    full_name: str
    role: Optional[UserRole] = None
    hourly_rate: Optional[float] = None
    cost_per_hour: Optional[float] = None
    available_hours_month: Optional[float] = None
    preferences: Optional[dict[str, Any]] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    short_name: Optional[str] = None
    birthday: Optional[date] = None
    job_title: Optional[str] = None
    morning_reminder_time: Optional[str] = None
    evening_reminder_time: Optional[str] = None
    onboarding_completed: Optional[bool] = None

    model_config = {"from_attributes": True}
