from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User
from backend.core.security import verify_password, hash_password, create_access_token, create_csrf_token, decode_access_token
from backend.core.rate_limiter import login_limiter
from backend.core.token_blacklist import token_blacklist
from backend.schemas.auth import ChangePassword, LoginRequest, TokenResponse, UserResponse
from backend.api.deps import get_current_user
from backend.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookies(response: Response, token: str) -> None:
    max_age = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    common_kwargs = {
        "max_age": max_age,
        "secure": settings.AUTH_COOKIE_SECURE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "path": settings.AUTH_COOKIE_PATH,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        **common_kwargs,
    )
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=create_csrf_token(),
        httponly=False,
        **common_kwargs,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_COOKIE_PATH,
    )
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_COOKIE_PATH,
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # Rate limit: 5 attempts per email+IP per 5 minutes (prevents lockout attacks)
    client_ip = request.client.host if request.client else "unknown"
    login_limiter.check(f"{body.email.lower()}:{client_ip}", max_requests=5, window_seconds=300)

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    if getattr(user, "password_reset_required", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password reset required")
    token = create_access_token({"sub": str(user.id)})
    _set_auth_cookies(response, token)
    # Don't expose token in response body — session is managed via httpOnly cookie
    return {"message": "ok"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password")
async def change_password(
    body: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    db.add(current_user)
    await db.commit()
    return {"message": "Password updated"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, _current_user: User = Depends(get_current_user)):
    # Extract and blacklist the current token
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if token:
        payload = decode_access_token(token)
        if payload and payload.get("jti") and payload.get("exp"):
            token_blacklist.add(payload["jti"], payload["exp"])
    _clear_auth_cookies(response)
    return None
