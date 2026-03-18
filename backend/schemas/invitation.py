from __future__ import annotations
from enum import Enum
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class InvitationRole(str, Enum):
    admin = "admin"
    member = "member"


class InvitationCreate(BaseModel):
    email: EmailStr
    role: InvitationRole = InvitationRole.member
    modules: list[str] = Field(default_factory=list)


class InvitationResponse(BaseModel):
    id: int
    email: str
    role: str
    invited_by: int
    inviter_name: Optional[str] = None
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationCreateResponse(InvitationResponse):
    token: str


class AcceptInvitationRequest(BaseModel):
    token: str
    full_name: str
    password: str = Field(min_length=8, max_length=128)


class PermissionItem(BaseModel):
    module: str
    can_read: bool = True
    can_write: bool = False


class UserPermissionsUpdate(BaseModel):
    permissions: list[PermissionItem]
