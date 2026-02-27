from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, UserRole, UserInvitation, UserPermission
from backend.core.security import hash_password
from backend.schemas.invitation import (
    InvitationCreate,
    InvitationResponse,
    InvitationCreateResponse,
    AcceptInvitationRequest,
    PermissionItem,
    UserPermissionsUpdate,
)
from backend.schemas.auth import UserResponse
from backend.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["invitations"])


def _inv_response(inv: UserInvitation) -> InvitationResponse:
    return InvitationResponse(
        id=inv.id,
        email=inv.email,
        role=inv.role.value,
        invited_by=inv.invited_by,
        inviter_name=inv.inviter.full_name if inv.inviter else None,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        created_at=inv.created_at,
    )


def _inv_create_response(inv: UserInvitation) -> InvitationCreateResponse:
    return InvitationCreateResponse(
        id=inv.id,
        email=inv.email,
        token=inv.token,
        role=inv.role.value,
        invited_by=inv.invited_by,
        inviter_name=inv.inviter.full_name if inv.inviter else None,
        expires_at=inv.expires_at,
        accepted_at=inv.accepted_at,
        created_at=inv.created_at,
    )


@router.get("/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """List all invitations (admin only)."""
    result = await db.execute(
        select(UserInvitation).order_by(UserInvitation.created_at.desc())
    )
    return [_inv_response(i) for i in result.scalars().all()]


@router.post("/invitations", response_model=InvitationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Create a new invitation (admin only)."""
    # Check if email is already registered
    existing_user = await db.execute(select(User).where(User.email == body.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check for pending invitation
    existing_inv = await db.execute(
        select(UserInvitation)
        .where(UserInvitation.email == body.email)
        .where(UserInvitation.accepted_at.is_(None))
        .where(UserInvitation.expires_at > datetime.utcnow())
    )
    if existing_inv.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Pending invitation already exists for this email")

    token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        email=body.email,
        token=token,
        role=UserRole(body.role),
        invited_by=current_user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    return _inv_create_response(invitation)


@router.post("/invitations/accept", response_model=UserResponse)
async def accept_invitation(
    body: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Accept an invitation and create a user account."""
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == body.token)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")
    if invitation.accepted_at:
        raise HTTPException(status_code=400, detail="Invitation already used")
    if invitation.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invitation expired")

    # Create user
    user = User(
        email=invitation.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=invitation.role,
        invited_by=invitation.invited_by,
    )
    db.add(user)
    await db.flush()  # Get user.id

    # Mark invitation as accepted
    invitation.accepted_at = datetime.utcnow()

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Revoke a pending invitation (admin only)."""
    result = await db.execute(select(UserInvitation).where(UserInvitation.id == invitation_id))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    await db.delete(invitation)
    await db.commit()


@router.get("/users/{user_id}/permissions", response_model=list[PermissionItem])
async def get_user_permissions(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Get permissions for a user (admin only)."""
    result = await db.execute(
        select(UserPermission).where(UserPermission.user_id == user_id)
    )
    return [
        PermissionItem(module=p.module, can_read=p.can_read, can_write=p.can_write)
        for p in result.scalars().all()
    ]


@router.put("/users/{user_id}/permissions", response_model=list[PermissionItem])
async def update_user_permissions(
    user_id: int,
    body: UserPermissionsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Update permissions for a user (admin only). Replaces all existing permissions."""
    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Don't allow changing admin permissions
    if target_user.role == UserRole.admin:
        raise HTTPException(status_code=400, detail="Cannot modify admin permissions")

    # Delete existing permissions
    existing = await db.execute(
        select(UserPermission).where(UserPermission.user_id == user_id)
    )
    for perm in existing.scalars().all():
        await db.delete(perm)

    # Create new permissions
    new_perms = []
    for p in body.permissions:
        perm = UserPermission(
            user_id=user_id,
            module=p.module,
            can_read=p.can_read,
            can_write=p.can_write,
        )
        db.add(perm)
        new_perms.append(p)

    await db.commit()
    return new_perms
