"""Validation shared by every project writer that accepts an owner."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import User


async def validate_project_owner(db: AsyncSession, owner_id: int | None) -> None:
    """Accept an explicit NULL or an existing active user; never infer an owner."""
    if owner_id is None:
        return
    try:
        active = (await db.execute(
            select(User.is_active).where(User.id == owner_id)
            .with_for_update(read=True, nowait=True)
        )).scalar_one_or_none()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise HTTPException(
                409, "El responsable está cambiando; vuelve a intentarlo",
            ) from exc
        raise
    if active is None:
        raise HTTPException(422, "El responsable seleccionado no existe")
    if active is not True:
        raise HTTPException(422, "El responsable seleccionado no está activo")
