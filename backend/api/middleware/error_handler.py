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
from sqlalchemy.exc import DataError, IntegrityError

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — log full traceback, return JSON."""
    ref = uuid.uuid4().hex[:8]

    # Extract user ID if available (set by auth middleware / dependency)
    user_id = getattr(request.state, "user_id", None)

    # --- DataError: value too long, invalid input, etc. → 422 --------
    if isinstance(exc, DataError):
        logger.warning(
            "DataError[%s] %s %s (user=%s): %s",
            ref, request.method, request.url.path, user_id, exc,
        )
        detail = "Datos inválidos"
        err_str = str(exc)
        if "value too long" in err_str or "too long" in err_str:
            detail = "Uno o más campos exceden la longitud máxima permitida"
        elif "invalid input" in err_str:
            detail = "Formato de datos inválido"
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "ref": ref},
        )

    # --- IntegrityError: FK violation, unique constraint → 409 -------
    if isinstance(exc, IntegrityError):
        logger.warning(
            "IntegrityError[%s] %s %s (user=%s): %s",
            ref, request.method, request.url.path, user_id, exc,
        )
        detail = "Conflicto de datos (duplicado o referencia inválida)"
        err_str = str(exc)
        if "unique" in err_str.lower() or "duplicate" in err_str.lower():
            detail = "Ya existe un registro con estos datos"
        elif "foreign key" in err_str.lower():
            detail = "Referencia a un registro que no existe"
        return JSONResponse(
            status_code=409,
            content={"detail": detail, "ref": ref},
        )

    # --- Everything else: genuine 500 --------------------------------
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
