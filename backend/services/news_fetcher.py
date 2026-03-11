"""RSS feed fetcher for industry news."""
from __future__ import annotations

import logging
from datetime import date, datetime

import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import IndustryNews, NewsFeed

logger = logging.getLogger(__name__)


def _parse_published_date(entry: dict) -> date:
    """Extract a date from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return date.today()


def _extract_summary(entry: dict, max_len: int = 500) -> str | None:
    """Extract a plain-text summary from a feedparser entry."""
    raw = entry.get("summary") or entry.get("description") or ""
    # Strip HTML tags naively
    import re
    text = re.sub(r"<[^>]+>", "", raw).strip()
    return text[:max_len] if text else None


async def fetch_single_feed(db: AsyncSession, feed: NewsFeed) -> int:
    """Fetch one RSS feed and create new IndustryNews articles. Returns count of new articles."""
    try:
        parsed = feedparser.parse(feed.url)
    except Exception as e:
        logger.error("Failed to parse feed %s (%s): %s", feed.name, feed.url, e)
        return 0

    if parsed.bozo and not parsed.entries:
        logger.warning("Feed %s returned no entries (bozo: %s)", feed.name, parsed.bozo_exception)
        return 0

    # Get existing URLs for dedup
    result = await db.execute(
        select(IndustryNews.url).where(IndustryNews.url.isnot(None))
    )
    existing_urls = {r[0] for r in result.all()}

    created = 0
    for entry in parsed.entries:
        url = entry.get("link", "").strip()
        if not url or url in existing_urls:
            continue

        title = (entry.get("title") or "Sin título").strip()[:300]
        published = _parse_published_date(entry)
        content = _extract_summary(entry)

        article = IndustryNews(
            title=title,
            url=url,
            content=content,
            published_date=published,
            feed_id=feed.id,
        )
        db.add(article)
        existing_urls.add(url)
        created += 1

    # Update last_fetched_at
    feed.last_fetched_at = datetime.utcnow()
    await db.commit()

    if created:
        logger.info("Feed '%s': %d new article(s)", feed.name, created)
    return created


async def fetch_all_feeds(db: AsyncSession) -> dict:
    """Fetch all enabled feeds. Returns summary stats."""
    result = await db.execute(
        select(NewsFeed).where(NewsFeed.enabled.is_(True))
    )
    feeds = result.scalars().all()

    total_new = 0
    feeds_processed = 0
    for feed in feeds:
        count = await fetch_single_feed(db, feed)
        total_new += count
        feeds_processed += 1

    return {
        "feeds_processed": feeds_processed,
        "new_articles": total_new,
    }
