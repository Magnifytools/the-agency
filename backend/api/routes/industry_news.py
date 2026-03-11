from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, IndustryNews, NewsFeed
from backend.schemas.industry_news import (
    IndustryNewsCreate,
    IndustryNewsUpdate,
    IndustryNewsResponse,
)
from backend.schemas.news_feed import NewsFeedCreate, NewsFeedUpdate, NewsFeedResponse
from backend.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/api/news", tags=["industry-news"])


@router.get("", response_model=list[IndustryNewsResponse])
async def list_news(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(IndustryNews).order_by(IndustryNews.published_date.desc()).limit(limit)
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

    _UPDATABLE_NEWS_FIELDS = {"title", "published_date", "content", "url"}
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in _UPDATABLE_NEWS_FIELDS:
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


# --- RSS Feeds ---

@router.get("/feeds", response_model=list[NewsFeedResponse])
async def list_feeds(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(NewsFeed).order_by(NewsFeed.name))
    return result.scalars().all()


@router.post("/feeds", response_model=NewsFeedResponse, status_code=201)
async def create_feed(
    body: NewsFeedCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    feed = NewsFeed(**body.model_dump())
    db.add(feed)
    await db.commit()
    await db.refresh(feed)
    return feed


@router.put("/feeds/{feed_id}", response_model=NewsFeedResponse)
async def update_feed(
    feed_id: int,
    body: NewsFeedUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(NewsFeed).where(NewsFeed.id == feed_id))
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(feed, field, value)
    await db.commit()
    await db.refresh(feed)
    return feed


@router.delete("/feeds/{feed_id}", status_code=204)
async def delete_feed(
    feed_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(NewsFeed).where(NewsFeed.id == feed_id))
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    await db.delete(feed)
    await db.commit()


@router.post("/fetch")
async def fetch_feeds(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    from backend.services.news_fetcher import fetch_all_feeds
    result = await fetch_all_feeds(db)
    return result
