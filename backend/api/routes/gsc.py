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


async def _connections(db: AsyncSession) -> list[GscConnection]:
    return list((await db.scalars(select(GscConnection).order_by(GscConnection.id))).all())


async def _connected_or_409(db: AsyncSession) -> list[GscConnection]:
    connections = [c for c in await _connections(db) if c.status == "connected"]
    if not connections:
        raise HTTPException(status_code=409, detail="Search Console no está conectado")
    return connections


@router.get("/status")
async def gsc_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Cuentas conectadas y estado de importación de cada propiedad usada por un cliente activo."""
    connections = await _connections(db)
    users = dict((await db.execute(select(User.id, User.full_name).where(
        User.id.in_([c.connected_by for c in connections if c.connected_by])
    ))).all()) if connections else {}
    emails = {c.id: c.google_email for c in connections}

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
        "connections": [
            {
                "id": c.id,
                "status": c.status,
                "google_email": c.google_email,
                "connected_by": users.get(c.connected_by),
                "connected_at": c.connected_at,
            }
            for c in connections
        ],
        "sites": [
            {
                "site_url": site,
                "clients": by_site[site],
                "backfilled": bool(states.get(site) and states[site].backfilled_at),
                "last_data_date": states[site].last_data_date if site in states else None,
                "last_synced_at": states[site].last_synced_at if site in states else None,
                "error_code": states[site].error_code if site in states else None,
                "google_email": emails.get(states[site].connection_id) if site in states else None,
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


@router.post("/connections/{connection_id}/disconnect")
async def gsc_disconnect(connection_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Quita una cuenta. Los datos ya importados se conservan; sus propiedades
    pasan a la siguiente cuenta que las vea en la próxima importación."""
    connection = await db.get(GscConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    await db.delete(connection)
    await db.commit()
    return {"status": "disconnected"}


@router.get("/sites")
async def gsc_sites(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Propiedades que ven las cuentas conectadas, para elegir la del cliente."""
    _require_configured()
    connections = await _connected_or_409(db)
    accounts = [(c.id, c.google_email, c.refresh_token) for c in connections]
    await db.commit()
    sites: dict[str, dict] = {}
    for connection_id, email, token in accounts:
        try:
            listed = await gsc_service.list_sites(token)
        except gsc_service.GscAuthError:
            connection = await db.get(GscConnection, connection_id)
            if connection is not None:
                connection.status = "reconnect_required"
                await db.commit()
            continue
        except gsc_service.GscSiteError:
            continue
        for s in listed:
            sites.setdefault(s["site_url"], {**s, "google_email": email})
    return {"sites": [sites[k] for k in sorted(sites)]}


@router.post("/sync")
async def gsc_sync(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Importa ahora en vez de esperar a la pasada diaria."""
    _require_configured()
    await _connected_or_409(db)
    await db.commit()
    return await gsc_service.sync_all(async_session)
