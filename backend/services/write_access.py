"""Fresh write authorization for domain mutations that may wait on locks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.modules import is_enabled
from backend.db.models import User, UserPermission, UserRole


async def require_current_write(
    db: AsyncSession,
    actor: Any | None,
    modules: Iterable[str],
) -> None:
    """Recheck current write access after the caller's domain-row locks.

    A caller passing ``actor=None`` is an explicitly authorized automatic
    writer and owns that decision. Interactive callers are serialized against
    permission and account writers by a PostgreSQL ``FOR SHARE NOWAIT`` lock.
    """
    if actor is None:
        return

    required = tuple(sorted(set(modules)))
    try:
        row = (await db.execute(
            select(User.role, User.is_active)
            .where(User.id == actor.id)
            .with_for_update(read=True, nowait=True)
        )).one_or_none()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409,
                "Tus permisos están cambiando; vuelve a intentarlo",
            ) from exc
        raise

    if row is None or row.is_active is not True:
        raise HTTPException(403, "La cuenta no está activa")

    disabled = [module for module in required if not is_enabled(module)]
    if disabled:
        raise HTTPException(
            403,
            f"Módulo no disponible: {', '.join(disabled)}",
        )

    if row.role == UserRole.admin:
        return

    writable = set((await db.execute(
        select(UserPermission.module).where(
            UserPermission.user_id == actor.id,
            UserPermission.module.in_(required),
            UserPermission.can_write.is_(True),
        )
    )).scalars().all()) if required else set()
    missing = [module for module in required if module not in writable]
    if missing:
        raise HTTPException(
            403,
            f"Sin acceso de escritura al módulo: {', '.join(missing)}",
        )
