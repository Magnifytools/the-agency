"""Search Console propio: conectar la cuenta de la agencia y ver la importación."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_admin, require_module
from backend.config import settings
from backend.db.database import async_session, get_db
from backend.db.models import Client, ClientStatus, GscConnection, GscSiteSync, User
from backend.services import gsc_service

router = APIRouter(prefix="/api/gsc", tags=["search-console"])
logger = logging.getLogger(__name__)

_STATE_PURPOSE = "gsc"


def _sign_state(user_id: int) -> str:
    # Lleva el propósito firmado: un state de Calendar no vale aquí.
    msg = f"{_STATE_PURPOSE}:{user_id}:{int(time.time())}"
    sig = hmac.new(settings.SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{msg}:{sig}".encode()).decode()


def _verify_state(state: str, max_age: int = 600) -> int:
    purpose, user_id_s, ts_s, sig = base64.urlsafe_b64decode(state.encode()).decode().split(":")
    expected = hmac.new(
        settings.SECRET_KEY.encode(), f"{purpose}:{user_id_s}:{ts_s}".encode(), hashlib.sha256
    ).hexdigest()[:32]
    if purpose != _STATE_PURPOSE or not hmac.compare_digest(sig, expected):
        raise ValueError("bad signature")
    if time.time() - int(ts_s) > max_age:
        raise ValueError("expired")
    return int(user_id_s)


def _require_configured() -> None:
    if not gsc_service.configured():
        raise HTTPException(status_code=503, detail="Google OAuth no está configurado")


async def _connection_or_409(db: AsyncSession) -> GscConnection:
    connection = await db.get(GscConnection, 1)
    if connection is None:
        raise HTTPException(status_code=409, detail="Search Console no está conectado")
    return connection


@router.get("/status")
async def gsc_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Conexión y estado de importación de cada propiedad usada por un cliente activo."""
    connection = await db.get(GscConnection, 1)
    connected_by = None
    if connection is not None and connection.connected_by:
        connected_by = await db.scalar(select(User.full_name).where(User.id == connection.connected_by))

    clients = (await db.execute(
        select(Client.id, Client.name, Client.gsc_url)
        .where(Client.status == ClientStatus.active, Client.gsc_url.isnot(None))
        .order_by(Client.name)
    )).all()
    by_site: dict[str, list[dict]] = {}
    for row in clients:
        site = gsc_service.normalize_site_url(row.gsc_url)
        if site:
            by_site.setdefault(site, []).append({"id": row.id, "name": row.name})
    states = {
        s.site_url: s for s in (await db.scalars(
            select(GscSiteSync).where(GscSiteSync.site_url.in_(list(by_site)))
        )).all()
    } if by_site else {}

    return {
        "configured": gsc_service.configured(),
        "connection": None if connection is None else {
            "status": connection.status,
            "google_email": connection.google_email,
            "connected_by": connected_by,
            "connected_at": connection.connected_at,
        },
        "sites": [
            {
                "site_url": site,
                "clients": by_site[site],
                "backfilled": bool(states.get(site) and states[site].backfilled_at),
                "last_data_date": states[site].last_data_date if site in states else None,
                "last_synced_at": states[site].last_synced_at if site in states else None,
                "error_code": states[site].error_code if site in states else None,
            }
            for site in sorted(by_site)
        ],
    }


@router.get("/auth-url")
async def gsc_auth_url(current_user: User = Depends(require_admin)):
    _require_configured()
    return {"url": gsc_service.get_auth_url(_sign_state(current_user.id))}


@router.get("/callback")
async def gsc_callback(
    code: str | None = Query(None),
    state: str = Query(""),
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        user_id = _verify_state(state)
    except Exception:  # noqa: BLE001 — cualquier state roto es inválido
        return RedirectResponse(url="/settings?gsc=error&reason=invalid_state")
    if error == "access_denied":
        return RedirectResponse(url="/settings?gsc=cancelled")
    if error or not code:
        return RedirectResponse(url="/settings?gsc=error")

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.role.value != "admin":
        return RedirectResponse(url="/settings?gsc=error")
    try:
        refresh_token, email = await gsc_service.exchange_code(code)
    except ValueError as exc:
        reason = "&reason=no_refresh_token" if str(exc) == "no_refresh_token" else ""
        return RedirectResponse(url=f"/settings?gsc=error{reason}")

    await gsc_service.save_connection(db, refresh_token=refresh_token, email=email, user_id=user_id)
    await db.commit()
    logger.info("Search Console conectado por user_id=%s", user_id)
    return RedirectResponse(url="/settings?gsc=connected")


@router.post("/disconnect")
async def gsc_disconnect(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Quita la conexión. Los datos ya importados se conservan."""
    connection = await db.get(GscConnection, 1)
    if connection is not None:
        await db.delete(connection)
        await db.commit()
    return {"status": "disconnected"}


@router.get("/sites")
async def gsc_sites(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Propiedades a las que tiene acceso la cuenta conectada, para elegir la del cliente."""
    _require_configured()
    connection = await _connection_or_409(db)
    token = connection.refresh_token
    await db.commit()
    try:
        return {"sites": await gsc_service.list_sites(token)}
    except gsc_service.GscAuthError:
        connection = await db.get(GscConnection, 1)
        if connection is not None:
            connection.status = "reconnect_required"
            await db.commit()
        raise HTTPException(status_code=409, detail="Hay que volver a conectar Search Console")
    except gsc_service.GscSiteError as exc:
        raise HTTPException(status_code=502, detail=f"Search Console no respondió ({exc.code})")


@router.post("/sync")
async def gsc_sync(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Importa ahora en vez de esperar a la pasada diaria."""
    _require_configured()
    await _connection_or_409(db)
    await db.commit()
    return await gsc_service.sync_all(async_session)
