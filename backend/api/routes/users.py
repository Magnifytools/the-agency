from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.api.utils.db_helpers import safe_refresh
from backend.core.security import hash_password
from backend.db.database import get_db
from backend.db.models import Project, ProjectStatus, Task, TaskStatus, User, UserPermission, UserRole
from backend.schemas.invitation import PermissionItem, UserPermissionsUpdate
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.user import UserCreate, UserListResponse, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])

_MEMBER_UPDATABLE = {"full_name", "preferences", "region", "locality", "short_name", "birthday", "job_title", "morning_reminder_time", "evening_reminder_time", "onboarding_completed"}
_ADMIN_UPDATABLE = _MEMBER_UPDATABLE | {"role", "hourly_rate", "cost_per_hour", "available_hours_month", "is_active", "email", "weekly_hours"}

# Modules accepted by sync_user_permissions. Derived from the modules actually
# guarded by require_module(...) across api/routes/. Keep in sync when a new
# module is introduced — silent failure here means stored permissions never
# take effect because no route checks them.
_VALID_MODULES = frozenset({
    "billing", "clients", "communications", "dashboard", "digests",
    "finance_advisor", "finance_expenses", "finance_forecasts", "finance_import",
    "finance_income", "finance_taxes",
    "growth", "leads", "pm", "projects", "proposals", "reports", "tasks", "timesheet",
})


def _validate_permission_items(items: list[PermissionItem]) -> None:
    modules = [item.module for item in items]
    invalid = set(modules) - _VALID_MODULES
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Módulos no reconocidos: {sorted(invalid)}. Permitidos: {sorted(_VALID_MODULES)}",
        )
    duplicates = sorted({module for module in modules if modules.count(module) > 1})
    if duplicates:
        raise HTTPException(
            status_code=422,
            detail=f"Módulos duplicados: {duplicates}",
        )

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
                id=u.id, full_name=u.full_name, is_active=u.is_active,
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
    await db.flush()  # get user.id before adding permissions

    # Auto-grant default module permissions for non-admin users
    if user.role != UserRole.admin:
        default_modules = ["dashboard", "clients", "tasks", "projects", "timesheet", "pm"]
        for mod in default_modules:
            db.add(UserPermission(user_id=user.id, module=mod, can_read=True, can_write=True))

    await db.commit()
    await safe_refresh(db, user, log_context="users")
    return user


@router.get("/{user_id}/deactivation-impact", response_model=dict[str, int])
async def get_deactivation_impact(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if await db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    tasks = await db.scalar(
        select(func.count()).select_from(Task).where(
            Task.assigned_to == user_id,
            Task.retired_at.is_(None),
            Task.status != TaskStatus.completed,
        )
    )
    projects = await db.scalar(
        select(func.count()).select_from(Project).where(
            Project.owner_id == user_id,
            Project.status.not_in([ProjectStatus.completed, ProjectStatus.cancelled]),
        )
    )
    return {"open_tasks": tasks or 0, "portfolio_projects": projects or 0}


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

    # Non-admin can only edit their own profile
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes editar tu propio perfil")

    data = body.model_dump(exclude_unset=True)
    if "is_active" in data and current_user.role != UserRole.admin:
        raise HTTPException(403, "Solo admin puede cambiar el acceso")
    if data.get("is_active") is False and user_id == current_user.id:
        raise HTTPException(422, "No puedes desactivar tu propia cuenta")
    allowed = _ADMIN_UPDATABLE if current_user.role == UserRole.admin else _MEMBER_UPDATABLE

    # Coerce empty strings to None for date/nullable fields, and convert date strings to date objects
    for key in ("birthday",):
        if key in data:
            if data[key] == "" or data[key] is None:
                data[key] = None
            elif isinstance(data[key], str):
                data[key] = date_type.fromisoformat(data[key])

    for field, value in data.items():
        if field not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"No tienes permiso para modificar '{field}'",
            )
        setattr(user, field, value)
    await db.commit()
    await safe_refresh(db, user, log_context="users")
    return user


@router.post("/{user_id}/permissions", status_code=200)
async def sync_user_permissions(
    user_id: int,
    modules: list[str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin-only: set a user's module permissions to exactly the given list."""
    invalid = set(modules) - _VALID_MODULES
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Módulos no reconocidos: {sorted(invalid)}. Permitidos: {sorted(_VALID_MODULES)}",
        )
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
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


@router.get("/{user_id}/permissions", response_model=list[PermissionItem])
async def get_user_permissions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Return a user's module permissions from the always-on users API."""
    user_result = await db.execute(select(User.id).where(User.id == user_id))
    if user_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(UserPermission)
        .where(UserPermission.user_id == user_id)
        .order_by(UserPermission.module, UserPermission.id)
    )
    return [
        PermissionItem(module=p.module, can_read=p.can_read, can_write=p.can_write)
        for p in result.scalars().all()
    ]


@router.put("/{user_id}/permissions", response_model=list[PermissionItem])
async def update_user_permissions(
    user_id: int,
    body: UserPermissionsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Replace a member's permissions atomically from the always-on users API."""
    _validate_permission_items(body.permissions)

    user_result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    target_user = user_result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.role == UserRole.admin:
        raise HTTPException(status_code=400, detail="Cannot modify admin permissions")

    existing = await db.execute(
        select(UserPermission).where(UserPermission.user_id == user_id)
    )
    for permission in existing.scalars().all():
        await db.delete(permission)
    # Keep delete-before-insert ordering explicit if the database later gains
    # the natural (user_id, module) uniqueness constraint.
    await db.flush()

    new_permissions = [
        UserPermission(
            user_id=user_id,
            module=item.module,
            can_read=item.can_read,
            can_write=item.can_write,
        )
        for item in body.permissions
    ]
    db.add_all(new_permissions)
    await db.commit()
    return body.permissions


@router.post("/sync-default-permissions", status_code=200)
async def sync_default_permissions_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin-only: ensure ALL non-admin users have default module permissions.

    Useful when new modules are added — adds missing permissions without
    removing existing ones.
    """
    default_modules = ["dashboard", "clients", "tasks", "projects", "timesheet", "pm"]

    users_result = await db.execute(
        select(User)
        .where(User.role != UserRole.admin)
        .order_by(User.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    users = users_result.scalars().all()

    total_added = 0
    users_updated = []
    for user in users:
        perms_result = await db.execute(
            select(UserPermission.module).where(UserPermission.user_id == user.id)
        )
        existing_modules = {r[0] for r in perms_result.all()}

        added_for_user = []
        for mod in default_modules:
            if mod not in existing_modules:
                db.add(UserPermission(
                    user_id=user.id, module=mod, can_read=True, can_write=True,
                ))
                added_for_user.append(mod)
                total_added += 1

        if added_for_user:
            users_updated.append({"user_id": user.id, "name": user.full_name, "added": added_for_user})

    if total_added:
        await db.commit()

    return {
        "total_permissions_added": total_added,
        "users_updated": users_updated,
        "default_modules": default_modules,
    }
