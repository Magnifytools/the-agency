from __future__ import annotations
from pydantic import BaseModel


class PermissionItem(BaseModel):
    module: str
    can_read: bool = True
    can_write: bool = False


class UserPermissionsUpdate(BaseModel):
    permissions: list[PermissionItem]
