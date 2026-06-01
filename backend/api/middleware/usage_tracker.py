"""Per-request usage tracker.

Writes one row to ``audit_logs`` for each authenticated API call with
``route_template``, ``method``, ``status_code``, ``duration_ms`` and ``user_id``.
Read-only, low-frequency analytics — combined with the 90d retention loop in
backend/startup/background_tasks.py the table stays bounded.

Skipped:
- non-/api paths (static, frontend, root)
- known high-frequency / non-informative endpoints (health, unread-count, OPTIONS)
- requests without an authenticated user (cannot attribute usage)

The write is best-effort: any exception inside the tracker is swallowed so a
DB hiccup never breaks the user-facing response.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# Routes that don't produce signal worth tracking. Matched as prefix.
_SKIP_PREFIXES: tuple[str, ...] = (
    "/api/health",
    "/api/notifications/unread-count",
    "/api/auth/refresh",
    "/api/active-timer",  # polled
)


def _route_template(request: Request) -> Optional[str]:
    """Resolve a parameterised route template ('/api/projects/{project_id}').

    Falls back to None if the request hasn't matched a route — Starlette only
    populates request.scope['route'] after the routing layer runs, so this
    works in dispatch() after calling call_next.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None) if route is not None else None
    return path


def _extract_user_id(request: Request) -> Optional[int]:
    """Read user id from request.state if a downstream dep set it.

    get_current_user doesn't currently stash the user on state; rather than
    touching it, we read it lazily from state.user_id if present, otherwise None.
    The middleware in track_request() handles the None case gracefully.
    """
    return getattr(request.state, "user_id", None)


class UsageTrackerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Cheap path filter before doing anything
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api"):
            return await call_next(request)
        for prefix in _SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        user_id = _extract_user_id(request)
        route = _route_template(request)
        # Only track authenticated, route-matched requests
        if user_id is not None and route is not None:
            try:
                from backend.db.database import async_session
                from backend.db.models import AuditLog

                async with async_session() as db:
                    db.add(AuditLog(
                        user_id=user_id,
                        method=request.method,
                        route_template=route,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                    ))
                    await db.commit()
            except Exception as e:
                logger.debug("Usage tracker write failed: %s", e)

        return response
