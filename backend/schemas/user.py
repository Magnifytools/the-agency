from __future__ import annotations
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
    role: Optional[UserRole] = None
    preferences: Optional[dict[str, Any]] = None


class UserListResponse(BaseModel):
    id: int
    email: Optional[str] = None
    full_name: str
    role: Optional[UserRole] = None
    hourly_rate: Optional[float] = None
    preferences: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}
