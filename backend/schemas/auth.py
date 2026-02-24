from __future__ import annotations
from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


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

    model_config = {"from_attributes": True}
