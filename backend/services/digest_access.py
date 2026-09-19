"""Single authorization contract for digest sources and report policies."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import noload

from backend.db.models import ClientReportPolicy, User, UserPermission, UserRole, WeeklyDigest


def permission_exists(user_id: int, *, write: bool):
    capability = UserPermission.can_write if write else UserPermission.can_read
    return exists().where(
        UserPermission.user_id == user_id,
        UserPermission.module == "digests",
        capability.is_(True),
    )


async def user_has_digest_permission(db, user_id: int, *, write: bool) -> bool:
    role_active = (await db.execute(
        select(User.role, User.is_active).where(User.id == user_id)
    )).one_or_none()
    if not role_active or not role_active.is_active:
        return False
    if role_active.role == UserRole.admin:
        return True
    return bool(await db.scalar(select(permission_exists(user_id, write=write))))


async def validate_responsible(db, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    user = (await db.execute(
        select(User.id, User.is_active).where(User.id == user_id)
    )).one_or_none()
    if not user or not user.is_active or not await user_has_digest_permission(db, user_id, write=True):
        raise HTTPException(422, detail={"code": "invalid_responsible", "message": "El responsable debe estar activo y poder preparar resúmenes"})
    return None


async def is_current_responsible(db, *, client_id: int, actor_id: int) -> bool:
    return bool(await db.scalar(select(exists().where(
        ClientReportPolicy.client_id == client_id,
        ClientReportPolicy.responsible_user_id == actor_id,
    ))))


async def authorize_digest(db, digest_id: int, actor: User, *, write: bool, lock: bool = False) -> WeeklyDigest:
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Usuario desactivado o no disponible")
    fresh_actor = (await db.execute(select(User.role, User.is_active).where(User.id == actor.id))).one_or_none()
    if not fresh_actor or not fresh_actor.is_active or not await user_has_digest_permission(db, actor.id, write=write):
        raise HTTPException(403, "Sin permiso para este resumen")
    stmt = select(WeeklyDigest).where(WeeklyDigest.id == digest_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    digest = (await db.execute(stmt)).scalar_one_or_none()
    if not digest:
        raise HTTPException(404, "Digest not found")
    if fresh_actor.role != UserRole.admin and digest.created_by != actor.id:
        if not await is_current_responsible(db, client_id=digest.client_id, actor_id=actor.id):
            raise HTTPException(403, "No tienes acceso a este resumen")
    return digest


def digest_visibility_clause(actor: User):
    if actor.role == UserRole.admin:
        return None
    return or_(
        WeeklyDigest.created_by == actor.id,
        exists().where(
            ClientReportPolicy.client_id == WeeklyDigest.client_id,
            ClientReportPolicy.responsible_user_id == actor.id,
        ),
    )
