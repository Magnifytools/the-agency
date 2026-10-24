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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.db.database import get_db
from backend.db.models import AppSuggestion, AppSuggestionImage, User, UserRole
from backend.services.app_suggestions import record_app_suggestion
from backend.services.file_uploads import (
    INLINE_RASTER_MIME_TYPES, attachment_type, read_limited, stored_file_response_args,
)
from backend.services.notification_service import create_notification

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

MAX_TEXT = 4000
# Pantallazos: imágenes rasterizadas, como mucho 5 por sugerencia y 5 MB cada una.
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = INLINE_RASTER_MIME_TYPES - {"image/avif"}


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


class SuggestionImage(BaseModel):
    id: int
    name: str
    size_bytes: int


class SuggestionResponse(BaseModel):
    id: int
    text: str
    page_path: Optional[str]
    author_id: Optional[int]
    author_name: Optional[str]
    created_at: datetime
    done_at: Optional[datetime]
    done_by_name: Optional[str]
    images: list[SuggestionImage] = []


def _name(user: Optional[User]) -> Optional[str]:
    return (user.short_name or user.full_name) if user else None


async def _responses(db: AsyncSession, rows: list[AppSuggestion]) -> list[SuggestionResponse]:
    ids = {i for r in rows for i in (r.author_id, r.done_by) if i is not None}
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()} if ids else {}
    images: dict[int, list[SuggestionImage]] = {}
    if rows:
        for image in (await db.execute(
            select(AppSuggestionImage.id, AppSuggestionImage.suggestion_id, AppSuggestionImage.name,
                   AppSuggestionImage.size_bytes)
            .where(AppSuggestionImage.suggestion_id.in_([r.id for r in rows]))
            .order_by(AppSuggestionImage.id)
        )).all():
            images.setdefault(image.suggestion_id, []).append(
                SuggestionImage(id=image.id, name=image.name, size_bytes=image.size_bytes))
    return [
        SuggestionResponse(
            id=r.id, text=r.text, page_path=r.page_path,
            author_id=r.author_id, author_name=_name(users.get(r.author_id)),
            created_at=r.created_at, done_at=r.done_at, done_by_name=_name(users.get(r.done_by)),
            images=images.get(r.id, []),
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


async def _visible_suggestion(db: AsyncSession, suggestion_id: int, user: User) -> AppSuggestion:
    """La sugerencia, si quien pide es admin o quien la escribió; si no, el mismo 404."""
    row = await db.get(AppSuggestion, suggestion_id)
    if row is None or (user.role != UserRole.admin and row.author_id != user.id):
        raise HTTPException(status_code=404, detail="Sugerencia no encontrada")
    return row


@router.post("/{suggestion_id}/images", response_model=SuggestionImage, status_code=201)
async def add_image(
    suggestion_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Añade un pantallazo (PNG, JPG, GIF o WebP) a una sugerencia propia (o de cualquiera, si es admin)."""
    row = await _visible_suggestion(db, suggestion_id, user)
    mime = attachment_type(file.filename or "")
    if mime not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Sólo se pueden adjuntar imágenes (PNG, JPG, GIF o WebP)")
    count = await db.scalar(select(func.count()).select_from(AppSuggestionImage)
                            .where(AppSuggestionImage.suggestion_id == row.id))
    if count >= MAX_IMAGES:
        raise HTTPException(status_code=409, detail=f"Como mucho {MAX_IMAGES} imágenes por sugerencia")
    content = await read_limited(file, MAX_IMAGE_BYTES)
    if not content:
        raise HTTPException(status_code=400, detail="La imagen está vacía")
    image = AppSuggestionImage(suggestion_id=row.id, name=file.filename, mime_type=mime,
                               size_bytes=len(content), content=content)
    db.add(image)
    await db.commit()
    return SuggestionImage(id=image.id, name=image.name, size_bytes=image.size_bytes)


@router.get("/{suggestion_id}/images/{image_id}")
async def get_image(
    suggestion_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _visible_suggestion(db, suggestion_id, user)
    image = await db.get(AppSuggestionImage, image_id)
    if image is None or image.suggestion_id != suggestion_id:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    args = stored_file_response_args(image.name, image.mime_type, inline=True)
    args["headers"]["Cache-Control"] = "private, max-age=3600"
    return Response(content=image.content, **args)
