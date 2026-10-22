"""Search Console propio: conectar la cuenta de la agencia y ver la importación."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_admin, require_module
from backend.config import settings
from backend.db.database import async_session, get_db
from backend.db.models import (
    Client, ClientStatus, Ga4Daily, Ga4LeadDaily, Ga4PropertySync, GscConnection, GscDaily, GscDetailSync,
    GscPageDaily, GscQueryDaily, GscQueryMonthly, GscSiteSync, User,
)
from backend.services import gsc_detail_service, gsc_service
from backend.services.job_catalog import job_definitions
from backend.services.job_runtime import JOB_LOCK_NAMESPACE
from backend.services.google_oauth import plain_refresh_token, revoke_token

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
    details = {
        s.site_url: s for s in (await db.scalars(
            select(GscDetailSync).where(GscDetailSync.site_url.in_(list(by_site)))
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
                # Detalle por consulta y página (120 días, job `gsc_detail`).
                "detail": {
                    "backfilled_at": details[site].backfilled_at,
                    "last_data_date": details[site].last_data_date,
                    "error_code": details[site].error_code,
                    "query_rows": details[site].query_rows,
                    "page_rows": details[site].page_rows,
                } if site in details else None,
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


class DisconnectRequest(BaseModel):
    # Borrar también las cifras de las propiedades que se importaban con esta cuenta.
    purge_data: bool = False


async def _purge_connection_data(db: AsyncSession, connection_id: int) -> dict:
    """Borra las cifras diarias (y su estado) de las propiedades de Search Console
    (totales, detalle por consulta y página e historial mensual por consulta, también
    el importado de The Engine) y GA4 (totales y leads por landing) que se importaban con esta
    cuenta. Si otra cuenta conectada también las ve, la próxima importación las
    vuelve a traer desde cero.

    Son ``delete()`` masivos: no pasan por el ORM y no entran en el Deshacer, a
    propósito (el admin lo ha pedido explícitamente al desconectar).
    """
    sites = list((await db.scalars(
        select(GscSiteSync.site_url).where(GscSiteSync.connection_id == connection_id)
    )).all())
    properties = list((await db.scalars(
        select(Ga4PropertySync.property_id).where(Ga4PropertySync.connection_id == connection_id)
    )).all())
    gsc_rows = query_rows = page_rows = ga4_rows = 0
    if sites:
        gsc_rows = (await db.execute(delete(GscDaily).where(GscDaily.site_url.in_(sites)))).rowcount or 0
        await db.execute(delete(GscSiteSync).where(GscSiteSync.site_url.in_(sites)))
        # El detalle por consulta y página de esas mismas propiedades.
        query_rows = (await db.execute(
            delete(GscQueryDaily).where(GscQueryDaily.site_url.in_(sites)))).rowcount or 0
        page_rows = (await db.execute(
            delete(GscPageDaily).where(GscPageDaily.site_url.in_(sites)))).rowcount or 0
        # Y su historial mensual por consulta (hasta 16 meses).
        await db.execute(delete(GscQueryMonthly).where(GscQueryMonthly.site_url.in_(sites)))
        await db.execute(delete(GscDetailSync).where(GscDetailSync.site_url.in_(sites)))
    if properties:
        ga4_rows = (await db.execute(delete(Ga4Daily).where(Ga4Daily.property_id.in_(properties)))).rowcount or 0
        # Y sus leads por landing (también los importados de The Engine).
        await db.execute(delete(Ga4LeadDaily).where(Ga4LeadDaily.property_id.in_(properties)))
        await db.execute(delete(Ga4PropertySync).where(Ga4PropertySync.property_id.in_(properties)))
    return {"gsc_sites": len(sites), "gsc_rows": gsc_rows, "gsc_query_rows": query_rows,
            "gsc_page_rows": page_rows, "ga4_properties": len(properties), "ga4_rows": ga4_rows}


@router.post("/connections/{connection_id}/disconnect")
async def gsc_disconnect(
    connection_id: int,
    body: DisconnectRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Quita una cuenta: borra su token y lo revoca en Google.

    Sin ``purge_data`` las cifras importadas se conservan y sus propiedades pasan
    a la siguiente cuenta que las vea. Con ``purge_data`` se borran las de las
    propiedades que se importaban con esta cuenta.
    """
    connection = await db.get(GscConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    token = plain_refresh_token(connection.refresh_token)
    # Antes de borrar la cuenta: el FK pone connection_id a NULL al borrarla.
    purged = await _purge_connection_data(db, connection_id) if body and body.purge_data else None
    await db.delete(connection)
    await db.commit()
    # Después de borrar: la copia local desaparece aunque Google no conteste.
    revoked = await revoke_token(token)
    if not revoked:
        logger.warning("Cuenta de Search Console %s borrada sin confirmación de revocación en Google", connection_id)
    return {"status": "disconnected", "google_revoked": revoked, "purged": purged}


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


@router.post("/detail-sync")
async def gsc_detail_sync(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    """Importa ahora el detalle por consulta y página (job `gsc_detail`).

    Toma el mismo lock que el job programado (17) mientras dura: dos pasadas a
    la vez borrarían e insertarían el mismo tramo y chocarían. El lock es de
    transacción y esta sesión no hace nada más; la importación usa las suyas.
    """
    _require_configured()
    await _connected_or_409(db)
    spec = next(d.spec for d in job_definitions() if d.spec.key == "gsc_detail")
    acquired = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:namespace, :lock_id)"),
                               {"namespace": JOB_LOCK_NAMESPACE, "lock_id": spec.lock_id})
    if not acquired:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ya hay una importación del detalle en marcha")
    try:
        return await gsc_detail_service.sync_all_detail(async_session)
    finally:
        await db.rollback()  # suelta el lock
