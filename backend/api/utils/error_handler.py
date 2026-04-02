import logging
import uuid
from functools import wraps

from fastapi import HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def safe_endpoint(func):
    """Decorator for route handlers that standardizes error handling.

    - Lets HTTPException pass through (FastAPI handles these).
    - Catches all other exceptions, logs them with a unique ref, and returns
      a generic 500 JSON response so that stack traces are never leaked.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise  # Let FastAPI handle these
        except Exception as e:
            ref = uuid.uuid4().hex[:12]
            logger.error(
                "Unhandled error ref=%s in %s: %s",
                ref,
                func.__name__,
                e,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={"error": "Error interno del servidor", "ref": ref},
            )

    return wrapper
