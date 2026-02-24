from __future__ import annotations
from typing import Optional

from pydantic import BaseModel
from backend.db.models import UserRole


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: UserRole = UserRole.member
    hourly_rate: Optional[float] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    hourly_rate: Optional[float] = None
    role: Optional[UserRole] = None


class UserListResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    hourly_rate: Optional[float] = None

    model_config = {"from_attributes": True}
