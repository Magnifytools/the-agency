"""Guardar una sugerencia para la app y avisar a los admins.

Lo usan el botón "Sugerencias" (``/api/suggestions``) y "Sugerencia para la
app" del inbox, para que las dos acaben en la misma lista. No hace commit.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AppSuggestion, User, UserRole
from backend.services.notification_service import create_notification

APP_SUGGESTION = "app_suggestion"


async def record_app_suggestion(
    db: AsyncSession, *, author: User, text: str, page_path: Optional[str] = None,
) -> AppSuggestion:
    row = AppSuggestion(author_id=author.id, text=text, page_path=page_path)
    db.add(row)
    await db.flush()
    admins = (await db.scalars(select(User.id).where(
        User.is_active.is_(True), User.role == UserRole.admin, User.id != author.id,
    ))).all()
    name = author.short_name or author.full_name
    for admin_id in admins:
        await create_notification(
            db, user_id=admin_id, type=APP_SUGGESTION,
            title=f"Sugerencia para la app de {name}",
            message=text,
            link_url="/sugerencias",
            entity_type=APP_SUGGESTION, entity_id=row.id,
        )
    return row
