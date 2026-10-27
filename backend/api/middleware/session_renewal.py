"""Pone en la respuesta la cookie renovada que decidió `get_current_user`."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.config import settings
from backend.core.auth_cookies import set_auth_cookies

# Logout borra la sesión: renovarla en esa misma respuesta la resucitaría.
_NEVER_RENEW = {"/api/auth/logout", "/api/auth/login"}


class SessionRenewalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        token = getattr(request.state, "renewed_token", None)
        path = request.url.path.rstrip("/")
        if token and response.status_code < 400 and path not in _NEVER_RENEW:
            set_auth_cookies(response, token, csrf_token=request.cookies.get(settings.CSRF_COOKIE_NAME))
        return response
