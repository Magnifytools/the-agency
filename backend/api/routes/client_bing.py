"""Bing Webmaster Tools de un cliente (`services/bing_live.py`).

Conexión (una cuenta de Bing por web): verla pide lectura de `clients`;
comprobar una clave, guardarla o quitarla, ser admin (guarda un secreto, como el
Slack del cliente). La clave entra como `SecretStr` y no vuelve nunca.

Comprobación: lectura de `clients`, mismo 404 que `/{id}/status`. POST a
propósito: gasta cuota de Bing y no debe repetirse sola al volver a la pestaña.
No guarda cifras.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_admin, require_module
from backend.core.rate_limiter import bing_live_limiter
from backend.core.security import encrypt_vault_secret
from backend.db.database import get_db
from backend.db.models import ClientBingConnection, User
from backend.services import bing_live

router = APIRouter(prefix="/api/clients", tags=["client-bing"])

# Por persona y minuto. Cada comprobación son hasta MAX_URLS + 1 llamadas a Bing.
LIMIT_PER_MINUTE = 10
_NO_STORE = {"Cache-Control": "no-store"}


class ApiKeyBody(BaseModel):
    api_key: SecretStr = Field(min_length=8, max_length=200)


class ConnectBody(ApiKeyBody):
    site_url: str = Field(min_length=8, max_length=500)


class PageQueriesBody(BaseModel):
    url: str = Field(min_length=8, max_length=500)


def _http(exc: bing_live.BingError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _key(body: ApiKeyBody) -> str:
    return body.api_key.get_secret_value().strip()


async def _view(db: AsyncSession, row: ClientBingConnection | None) -> dict:
    if row is None:
        return {"connected": False, "site_url": None, "status": None, "last_error": None,
                "connected_at": None, "connected_by_name": None}
    by = await db.get(User, row.connected_by) if row.connected_by else None
    return {
        "connected": True,
        "site_url": row.site_url,
        "status": row.status,
        "last_error": row.last_error,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "connected_by_name": (by.short_name or by.full_name) if by else None,
    }


@router.get("/{client_id}/bing/connection")
async def get_bing_connection(
    client_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("clients")),
):
    """Si la web tiene Bing conectado y con qué sitio. Nunca la clave."""
    await get_client_or_404(client_id, db)
    response.headers.update(_NO_STORE)
    return await _view(db, await db.get(ClientBingConnection, client_id))


@router.post("/{client_id}/bing/connection/sites")
async def bing_connection_sites(
    client_id: int,
    body: ApiKeyBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Sitios verificados de la cuenta de esa clave, sin guardar nada, y cuál es el del cliente."""
    client = await get_client_or_404(client_id, db)
    bing_live_limiter.check(admin.id, LIMIT_PER_MINUTE, 60)
    response.headers.update(_NO_STORE)
    try:
        sites = await bing_live.user_sites(_key(body))
    except bing_live.BingError as exc:
        raise _http(exc) from exc
    return {"sites": sites, "suggested": bing_live.suggested_site(sites, client)}


@router.put("/{client_id}/bing/connection")
async def put_bing_connection(
    client_id: int,
    body: ConnectBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Guarda la clave (cifrada) y el sitio. Sustituye la conexión anterior."""
    await get_client_or_404(client_id, db)
    bing_live_limiter.check(admin.id, LIMIT_PER_MINUTE, 60)
    response.headers.update(_NO_STORE)
    api_key = _key(body)
    site_url = body.site_url.strip()
    # Se vuelve a preguntar a Bing: la cuenta tiene que ver ESE sitio.
    await db.commit()
    try:
        sites = await bing_live.user_sites(api_key)
    except bing_live.BingError as exc:
        raise _http(exc) from exc
    if site_url not in sites:
        raise HTTPException(422, detail={"code": "unknown_site",
                                         "message": "Esa cuenta de Bing no tiene verificado ese sitio."})
    row = await db.get(ClientBingConnection, client_id)
    if row is None:
        row = ClientBingConnection(client_id=client_id)
        db.add(row)
    row.api_key = encrypt_vault_secret(api_key)
    row.site_url = site_url
    row.status = "ok"
    row.last_error = None
    row.connected_by = admin.id
    row.connected_at = datetime.now(UTC)
    await db.commit()
    return await _view(db, row)


@router.delete("/{client_id}/bing/connection")
async def delete_bing_connection(
    client_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Olvida la clave. En Bing sigue viva: se borra allí si se quiere cortar el acceso."""
    await get_client_or_404(client_id, db)
    response.headers.update(_NO_STORE)
    row = await db.get(ClientBingConnection, client_id)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return await _view(db, None)


@router.post("/{client_id}/bing/check")
async def bing_check(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """Rastreo y rendimiento en Bing de las URLs vigiladas del cliente."""
    client = await get_client_or_404(client_id, db)
    bing_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await bing_live.check(db, client)
    except bing_live.BingError as exc:
        raise _http(exc) from exc


@router.post("/{client_id}/bing/page-queries")
async def bing_page_queries(
    client_id: int,
    body: PageQueriesBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("clients")),
):
    """Consultas de Bing de una de las URLs que se comprueban."""
    client = await get_client_or_404(client_id, db)
    bing_live_limiter.check(current_user.id, LIMIT_PER_MINUTE, 60)
    try:
        return await bing_live.page_queries(db, client, body.url.strip())
    except bing_live.BingError as exc:
        raise _http(exc) from exc
