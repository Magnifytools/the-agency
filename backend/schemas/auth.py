from __future__ import annotations
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PermissionResponse(BaseModel):
    module: str
    can_read: bool
    can_write: bool

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    hourly_rate: Optional[float] = None
    is_active: bool = True
    permissions: list[PermissionResponse] = []
    preferences: Optional[dict] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    short_name: Optional[str] = None
    birthday: Optional[str] = None
    job_title: Optional[str] = None
    morning_reminder_time: Optional[str] = None
    evening_reminder_time: Optional[str] = None
    onboarding_completed: Optional[bool] = None

    model_config = {"from_attributes": True}
