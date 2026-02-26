from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, UserPermission, UserRole
from backend.schemas.user import UserCreate, UserUpdate, UserListResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_admin
from backend.core.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

@router.get("", response_model=PaginatedResponse[UserListResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    if current_user.role == UserRole.admin:
        # Admin sees all fields
        query = select(User).order_by(User.full_name).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return PaginatedResponse(items=result.scalars().all(), total=total, page=page, page_size=page_size)
    else:
        # Non-admin: return only id + full_name (minimal for task/lead assignment pickers)
        query = select(User).order_by(User.full_name).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        users = result.scalars().all()
        sanitized = [
            UserListResponse(
                id=u.id, full_name=u.full_name,
                email=None, role=None, hourly_rate=None,
            )
            for u in users
        ]
        return PaginatedResponse(items=sanitized, total=total, page=page, page_size=page_size)


@router.post("", response_model=UserListResponse, status_code=201)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only admin can create users
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Solo admin puede crear usuarios")
        
    # Check if email exists
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")
        
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        hourly_rate=body.hourly_rate,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserListResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Non-admin can only view their own profile
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes ver tu propio perfil")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserListResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    data = body.model_dump(exclude_unset=True)

    # Only admin can change roles
    if "role" in data and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Solo admin puede cambiar roles")

    # Non-admin can only edit their own profile
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes editar tu propio perfil")

    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/permissions", status_code=200)
async def sync_user_permissions(
    user_id: int,
    modules: list[str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin-only: set a user's module permissions to exactly the given list."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Load current permissions
    perms_result = await db.execute(
        select(UserPermission).where(UserPermission.user_id == user_id)
    )
    existing = {p.module: p for p in perms_result.scalars().all()}
    desired = set(modules)

    # Remove extras
    removed = []
    for mod, perm in existing.items():
        if mod not in desired:
            await db.delete(perm)
            removed.append(mod)

    # Add missing
    added = []
    for mod in desired:
        if mod not in existing:
            db.add(UserPermission(user_id=user_id, module=mod, can_read=True, can_write=True))
            added.append(mod)

    await db.commit()

    return {
        "user_id": user_id,
        "modules": sorted(desired),
        "added": sorted(added),
        "removed": sorted(removed),
    }
