from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.deps import require_admin
from backend.api.middleware.audit_log import log_audit
from backend.api.utils.db_helpers import safe_refresh
from backend.core.rate_limiter import login_limiter
from backend.core.security import hash_password
from backend.db.database import get_db
from backend.db.models import User, UserInvitation, UserPermission, UserRole
from backend.schemas.auth import UserResponse
from backend.schemas.invitation import (
    AcceptInvitationRequest,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationResponse,
)

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
        select(UserInvitation)
        .options(selectinload(UserInvitation.inviter))
        .order_by(UserInvitation.created_at.desc())
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
        .where(UserInvitation.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))
    )
    if existing_inv.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Pending invitation already exists for this email")

    token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        email=body.email,
        token=token,
        role=UserRole(body.role.value),
        invited_by=current_user.id,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    db.add(invitation)
    await db.commit()
    await safe_refresh(db, invitation, log_context="invitations")

    log_audit(current_user.id, "invite", "user", invitation.id, details=f"email={body.email} role={body.role.value}")
    # Reload with relationships for response
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.id == invitation.id)
        .options(selectinload(UserInvitation.inviter))
    )
    return _inv_create_response(result.scalar_one())


@router.post("/invitations/accept", response_model=UserResponse)
async def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Accept an invitation and create a user account."""
    # Rate limit: 5 attempts per IP per 15 minutes (brute-force token protection)
    client_ip = request.client.host if request.client else "unknown"
    login_limiter.check(f"inv:{client_ip}", max_requests=5, window_seconds=900)

    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == body.token)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation token")
    if invitation.accepted_at:
        raise HTTPException(status_code=400, detail="Invitation already used")
    if invitation.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
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

    # Auto-grant default module permissions for non-admin users
    if user.role != UserRole.admin:
        default_modules = ["dashboard", "clients", "tasks", "projects", "timesheet", "pm", "digests"]
        for mod in default_modules:
            db.add(UserPermission(user_id=user.id, module=mod, can_read=True, can_write=True))

    # Mark invitation as accepted
    invitation.accepted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await safe_refresh(db, user, log_context="invitations")

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
    log_audit(_user.id, "revoke_invitation", "user", invitation_id)


# Compatibility import for callers and concurrency tests that historically
# imported this writer from the invitations module. The HTTP routes themselves
# live on the always-registered users router.
from backend.api.routes.users import (  # noqa: F401
    get_user_permissions,
    update_user_permissions,
)
