from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, IndustryNews
from backend.schemas.industry_news import (
    IndustryNewsCreate,
    IndustryNewsUpdate,
    IndustryNewsResponse,
)
from backend.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/api/news", tags=["industry-news"])


@router.get("", response_model=list[IndustryNewsResponse])
async def list_news(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(IndustryNews).order_by(IndustryNews.published_date.desc())
    )
    return result.scalars().all()


@router.get("/{news_id}", response_model=IndustryNewsResponse)
async def get_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(IndustryNews).where(IndustryNews.id == news_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return item


@router.post("", response_model=IndustryNewsResponse, status_code=201)
async def create_news(
    body: IndustryNewsCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    item = IndustryNews(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/{news_id}", response_model=IndustryNewsResponse)
async def update_news(
    news_id: int,
    body: IndustryNewsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IndustryNews).where(IndustryNews.id == news_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{news_id}", status_code=204)
async def delete_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IndustryNews).where(IndustryNews.id == news_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    await db.delete(item)
    await db.commit()
