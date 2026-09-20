"""Shared condition contract; collectors do not commit or deliver messages."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_

from backend.db.models import User, UserPermission, UserRole


@dataclass(frozen=True)
class Condition:
    key: str
    kind: str
    entity_id: int | None
    title: str
    message: str
    fingerprint: str
    severity: str = "warning"
    entity_type: str = "task"
    entity_key: str | None = None
    href: str | None = None
    legacy_since: datetime | None = None


def module_permission(user_id, module: str, *, write: bool = False):
    capability = UserPermission.can_write if write else UserPermission.can_read
    return exists().where(
        User.id == user_id, User.is_active.is_(True),
        or_(User.role == UserRole.admin, exists().where(
            UserPermission.user_id == User.id,
            UserPermission.module == module,
            capability.is_(True),
        )),
    )
