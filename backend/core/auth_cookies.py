"""Cookies de sesión de la web: emitirlas, renovarlas y borrarlas."""
from datetime import datetime, timezone
from typing import Optional

from starlette.responses import Response

from backend.config import settings
from backend.core.security import create_access_token, create_csrf_token


def _cookie_kwargs() -> dict:
    return {
        "max_age": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        "secure": settings.AUTH_COOKIE_SECURE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "path": settings.AUTH_COOKIE_PATH,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }


def set_auth_cookies(response: Response, token: str, csrf_token: Optional[str] = None) -> None:
    """Pone la sesión. Al renovar se conserva el CSRF que ya tiene el navegador:
    cambiarlo rompería las peticiones que ya salieron con el anterior."""
    kwargs = _cookie_kwargs()
    response.set_cookie(key=settings.AUTH_COOKIE_NAME, value=token, httponly=True, **kwargs)
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME, value=csrf_token or create_csrf_token(), httponly=False, **kwargs,
    )


def clear_auth_cookies(response: Response) -> None:
    for key in (settings.AUTH_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(key=key, domain=settings.AUTH_COOKIE_DOMAIN, path=settings.AUTH_COOKIE_PATH)


def renewed_token(payload: dict, now: Optional[datetime] = None) -> Optional[str]:
    """Sesión deslizante: un token de cookie al que le queda menos de la mitad
    de su vida se cambia por uno nuevo. Quien usa la app no se queda fuera a
    media tarea; quien la deja más de ACCESS_TOKEN_EXPIRE_MINUTES, sí."""
    exp = payload.get("exp")
    sub = payload.get("sub")
    if exp is None or sub is None:
        return None
    now = now or datetime.now(timezone.utc)
    remaining = float(exp) - now.timestamp()
    if remaining >= settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 / 2:
        return None
    return create_access_token({"sub": str(sub)})
