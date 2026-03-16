"""Database helpers to prevent recurring 500 errors.

The most common pattern causing 500s in this codebase is:

    await db.commit()
    await db.refresh(obj)  # ← Explodes if relationships fail to load

`safe_refresh` wraps this in a try/except so the response still works
even when relationship loading fails after a successful commit.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

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
            "safe_refresh failed%s: %s — continuing with stale object",
            f" [{log_context}]" if log_context else "",
            exc,
        )
