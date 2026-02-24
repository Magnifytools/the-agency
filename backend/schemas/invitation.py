from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class InvitationCreate(BaseModel):
    email: str
    role: str = "member"
    modules: list[str] = []


class InvitationResponse(BaseModel):
    id: int
    email: str
    token: str
    role: str
    invited_by: int
    inviter_name: Optional[str] = None
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AcceptInvitationRequest(BaseModel):
    token: str
    full_name: str
    password: str


class PermissionItem(BaseModel):
    module: str
    can_read: bool = True
    can_write: bool = False


class UserPermissionsUpdate(BaseModel):
    permissions: list[PermissionItem]
