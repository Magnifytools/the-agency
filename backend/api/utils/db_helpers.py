"""Database helpers to prevent recurring 500 errors.

The most common pattern causing 500s in this codebase is:

    await db.commit()
    await db.refresh(obj)  # ← Explodes if relationships fail to load

`safe_refresh` wraps this in a try/except so the response still works
even when relationship loading fails after a successful commit.

IMPORTANT: After db.commit(), SQLAlchemy expires ALL attributes on the
object.  If safe_refresh catches an error, all attributes remain expired
and accessing ANY of them (even columns) will trigger a lazy load that
fails in async context → 500.  To prevent this, on failure we expunge
the object from the session so attribute access returns the last-known
Python-side values instead of triggering a DB round-trip.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


async def safe_refresh(
    db: AsyncSession,
    obj: Any,
    attribute_names: Sequence[str] | None = None,
    *,
    log_context: str = "",
) -> None:
    """Refresh an ORM object, swallowing errors from relationship loading.

    Use this after db.commit() when the commit already succeeded and the
    response should not fail just because a joined relationship can't be
    loaded (e.g., NULL FK, deleted parent, lazy-load issue).

    On failure the object is expunged from the session so that subsequent
    attribute access returns cached Python values instead of attempting a
    synchronous lazy-load (which crashes in async context).

    Args:
        db: The async session.
        obj: The ORM object to refresh.
        attribute_names: Optional list of attribute names to refresh.
        log_context: A short label for log messages (e.g., "timer_start").
    """
    try:
        if attribute_names:
            await db.refresh(obj, list(attribute_names))
        else:
            await db.refresh(obj)
    except Exception as exc:
        logger.warning(
            "safe_refresh failed%s: %s — expunging object to prevent lazy-load 500s",
            f" [{log_context}]" if log_context else "",
            exc,
        )
        try:
            db.expunge(obj)
        except Exception:
            pass  # Already detached or session closed — nothing to do


async def reload_for_response(db: AsyncSession, model_class, obj_id: int, options=None):
    """Reload an ORM object by ID with explicit selectinload options.

    This is the safest pattern after commit: a fresh SELECT with eager
    loading instead of refresh on a potentially-expired object.

    Returns None if the object is not found (should never happen after
    a successful commit, but guards against race conditions).
    """
    from sqlalchemy import select

    stmt = select(model_class).where(model_class.id == obj_id)
    if options:
        stmt = stmt.options(*options)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
