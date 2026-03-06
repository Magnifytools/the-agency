from __future__ import annotations
from typing import Optional

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
    role: Optional[UserRole] = None
    # Restrict preferences to scalar values only (no nested objects)
    preferences: Optional[dict[str, str | int | float | bool | None]] = None


class UserListResponse(BaseModel):
    id: int
    email: Optional[str] = None
    full_name: str
    role: Optional[UserRole] = None
    hourly_rate: Optional[float] = None

    model_config = {"from_attributes": True}
