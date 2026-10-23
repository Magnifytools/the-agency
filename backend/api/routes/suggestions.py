"""Sugerencias: ideas y fallos de la app que el equipo deja dentro de The Agency.

Cualquiera con sesión puede enviar una; los admins las ven todas y las marcan
como hechas, el resto ve sólo las suyas y en qué quedaron. Al enviarla se avisa
a los admins en la campana (como la "Sugerencia para la app" del inbox, que
también acaba aquí) y al marcarla como hecha se avisa a quien la escribió.
Nada sale de la app.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.db.database import get_db
from backend.db.models import AppSuggestion, User, UserRole
from backend.services.app_suggestions import record_app_suggestion
from backend.services.notification_service import create_notification

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

MAX_TEXT = 4000


class SuggestionCreate(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT)
    page_path: Optional[str] = Field(None, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Escribe la sugerencia")
        return value

    @field_validator("page_path")
    @classmethod
    def _internal_path(cls, value: Optional[str]) -> Optional[str]:
        # Sólo una ruta de la app: se pinta como enlace en la lista.
        if not value or not value.startswith("/") or value.startswith("//"):
            return None
        return value


class SuggestionUpdate(BaseModel):
    done: bool


class SuggestionResponse(BaseModel):
    id: int
    text: str
    page_path: Optional[str]
    author_id: Optional[int]
    author_name: Optional[str]
    created_at: datetime
    done_at: Optional[datetime]
    done_by_name: Optional[str]


def _name(user: Optional[User]) -> Optional[str]:
    return (user.short_name or user.full_name) if user else None


async def _responses(db: AsyncSession, rows: list[AppSuggestion]) -> list[SuggestionResponse]:
    ids = {i for r in rows for i in (r.author_id, r.done_by) if i is not None}
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()} if ids else {}
    return [
        SuggestionResponse(
            id=r.id, text=r.text, page_path=r.page_path,
            author_id=r.author_id, author_name=_name(users.get(r.author_id)),
            created_at=r.created_at, done_at=r.done_at, done_by_name=_name(users.get(r.done_by)),
        )
        for r in rows
    ]


@router.get("", response_model=list[SuggestionResponse])
async def list_suggestions(
    status: Literal["open", "done", "all"] = Query("open"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(AppSuggestion)
    if user.role != UserRole.admin:
        query = query.where(AppSuggestion.author_id == user.id)
    if status == "open":
        query = query.where(AppSuggestion.done_at.is_(None))
    elif status == "done":
        query = query.where(AppSuggestion.done_at.is_not(None))
    rows = (await db.scalars(query.order_by(AppSuggestion.created_at.desc(), AppSuggestion.id.desc()).limit(500))).all()
    return await _responses(db, list(rows))


@router.post("", response_model=SuggestionResponse, status_code=201)
async def create_suggestion(
    body: SuggestionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await record_app_suggestion(db, author=user, text=body.text, page_path=body.page_path)
    await db.commit()
    await db.refresh(row)
    return (await _responses(db, [row]))[0]


@router.patch("/{suggestion_id}", response_model=SuggestionResponse)
async def update_suggestion(
    suggestion_id: int,
    body: SuggestionUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = (await db.execute(
        select(AppSuggestion).where(AppSuggestion.id == suggestion_id).with_for_update()
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Sugerencia no encontrada")
    if body.done and row.done_at is None:
        row.done_at = datetime.now(timezone.utc)
        row.done_by = admin.id
        if row.author_id is not None and row.author_id != admin.id:
            await create_notification(
                db, user_id=row.author_id, type="app_suggestion_done",
                title="Tu sugerencia está hecha",
                message=row.text,
                link_url="/sugerencias",
                entity_type="app_suggestion", entity_id=row.id,
            )
    elif not body.done:
        row.done_at = None
        row.done_by = None
    await db.commit()
    await db.refresh(row)
    return (await _responses(db, [row]))[0]
