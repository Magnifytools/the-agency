from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, IndustryNews, NewsSource
from backend.schemas.industry_news import (
    IndustryNewsCreate,
    IndustryNewsUpdate,
    IndustryNewsResponse,
)
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/news", tags=["industry-news"])


# --- URL Extraction ---

class ExtractRequest(BaseModel):
    url: str


class ExtractResponse(BaseModel):
    title: str | None = None
    content: str | None = None
    published_date: str | None = None


@router.post("/extract", response_model=ExtractResponse)
async def extract_url(
    body: ExtractRequest,
    _: User = Depends(get_current_user),
):
    """Extract title and description from a URL using BeautifulSoup."""
    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(body.url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; MagnifyBot/1.0)",
            })
            resp.raise_for_status()
    except Exception as e:
        logging.warning("URL extraction failed for %s: %s", body.url, e)
        raise HTTPException(status_code=422, detail=f"No se pudo acceder a la URL: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title: og:title > <title>
    title = None
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Description: og:description > meta description
    content = None
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        content = og_desc["content"].strip()
    else:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            content = meta_desc["content"].strip()

    # Published date: article:published_time
    published_date = None
    pub_meta = soup.find("meta", property="article:published_time")
    if pub_meta and pub_meta.get("content"):
        raw = pub_meta["content"].strip()
        published_date = raw[:10] if len(raw) >= 10 else raw

    return ExtractResponse(title=title, content=content, published_date=published_date)


# --- News CRUD ---

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
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(IndustryNews).where(IndustryNews.id == news_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    await db.delete(item)
    await db.commit()


# --- News Sources CRUD ---

class NewsSourceCreate(BaseModel):
    name: str
    url: str
    category: str | None = None

class NewsSourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    category: str | None = None

class NewsSourceResponse(BaseModel):
    id: int
    name: str
    url: str
    category: str | None = None
    created_at: str | None = None
    model_config = {"from_attributes": True}


@router.get("/sources", response_model=list[NewsSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(NewsSource).order_by(NewsSource.name))
    return result.scalars().all()


@router.post("/sources", response_model=NewsSourceResponse, status_code=201)
async def create_source(
    body: NewsSourceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source = NewsSource(**body.model_dump())
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.put("/sources/{source_id}", response_model=NewsSourceResponse)
async def update_source(
    source_id: int,
    body: NewsSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(NewsSource).where(NewsSource.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(NewsSource).where(NewsSource.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
