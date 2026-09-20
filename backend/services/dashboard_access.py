"""Access decisions for dashboard metrics and financial projections."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from backend.api.deps import get_current_user
from backend.core.modules import is_enabled
from backend.db.models import User, UserRole


def has_module_read(user: User, module: str) -> bool:
    """Return whether a dashboard metric may read its source module."""
    if not is_enabled(module):
        return False
    if user.role == UserRole.admin:
        return True
    return any(
        permission.module == module and permission.can_read
        for permission in (user.permissions or [])
    )


def ensure_source_access(user: User, *modules: str) -> None:
    """Reject a standalone dashboard view when any required source is unavailable."""
    if any(not is_enabled(module) for module in modules):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if any(not has_module_read(user, module) for module in modules):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin acceso a las fuentes de este panel",
        )


async def require_financial_dashboard_access(
    current_user: User = Depends(get_current_user),
) -> User:
    """Financial dashboard data exists only for admins while finance is enabled."""
    if not is_enabled("finance"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return current_user
