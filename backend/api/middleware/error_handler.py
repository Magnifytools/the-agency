"""Global error handler middleware for FastAPI.

Catches all unhandled exceptions and returns a structured JSON response
with a correlation ID instead of a raw 500 HTML page.  This makes errors
debuggable (grep logs by ref) without leaking internals to the client.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — log full traceback, return JSON."""
    ref = uuid.uuid4().hex[:8]

    # Extract user ID if available (set by auth middleware / dependency)
    user_id = getattr(request.state, "user_id", None)

    logger.error(
        "Unhandled[%s] %s %s (user=%s): %s",
        ref,
        request.method,
        request.url.path,
        user_id,
        exc,
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Error interno del servidor",
            "ref": ref,
        },
    )
