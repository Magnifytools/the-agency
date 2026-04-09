from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.security import decode_access_token
from backend.core.token_blacklist import token_blacklist
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import User, UserRole, Client, UserPermission

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    jti = payload.get("jti")
    if jti and token_blacklist.is_blacklisted(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(
        select(User).where(User.id == int(user_id)).options(selectinload(User.permissions))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is deactivated")
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return current_user


def require_module(module: str, write: bool = False):
    """Dependency factory: checks if user has access to a module.
    If write=True, checks can_write; otherwise checks can_read.
    Admin users bypass permission checks."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.admin:
            return current_user
        # Safely access permissions — avoid 500 if lazy-load fails
        try:
            perms = current_user.permissions
        except Exception:
            perms = []
        for perm in perms:
            if perm.module == module:
                if write and perm.can_write:
                    return current_user
                if not write and perm.can_read:
                    return current_user
        action = "escritura" if write else "lectura"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin acceso de {action} al módulo: {module}. Pide a un administrador que te dé acceso.",
        )

    return checker


async def get_client_or_404(client_id: int, db: AsyncSession) -> Client:
    """Fetch a client by ID or raise 404."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


# ── Pagination ─────────────────────────────────────────────

class PaginationParams:
    """Reusable pagination dependency. Use as Depends(PaginationParams)."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size
        self.limit = page_size
