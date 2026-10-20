"""Enlace de sólo lectura para el cliente: gestión (Ajustes del cliente) y vista pública."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_module
from backend.core.rate_limiter import public_link_limiter
from backend.db.database import get_db
from backend.db.models import Client, User
from backend.services import client_share_links as links
from backend.services.dashboard_access import has_module_read

router = APIRouter(tags=["client-share-links"])

# El enlace no debe acabar en buscadores, cachés compartidas ni en el Referer.
_PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
_NOT_FOUND = "Este enlace no existe o ya no está activo"


async def _client_or_404(db: AsyncSession, client_id: int, *, lock: bool = False) -> int:
    query = select(Client.id).where(Client.id == client_id)
    if lock:
        # Serializa dos "Crear enlace" a la vez sobre el mismo cliente.
        query = query.with_for_update()
    if await db.scalar(query) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client_id


async def _status(db: AsyncSession, client_id: int) -> dict:
    link = await links.active_link(db, client_id)
    if link is None:
        return {"active": False, "created_at": None, "created_by_name": None, "last_viewed_at": None}
    created_at, created_by, last_viewed_at = link.created_at, link.created_by, link.last_viewed_at
    creator = await db.scalar(select(User.full_name).where(User.id == created_by)) if created_by else None
    return {
        "active": True,
        "created_at": created_at.isoformat(),
        "created_by_name": creator,
        "last_viewed_at": last_viewed_at.isoformat() if last_viewed_at else None,
    }


@router.get("/api/clients/{client_id}/share-link")
async def share_link_status(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("clients")),
):
    """Si hay enlace activo y desde cuándo. El token no se vuelve a enseñar nunca."""
    await _client_or_404(db, client_id)
    return await _status(db, client_id)


@router.post("/api/clients/{client_id}/share-link", status_code=status.HTTP_201_CREATED)
async def create_share_link(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module("clients", write=True)),
):
    """Crea el enlace (o lo regenera: el anterior deja de funcionar al momento).

    Pide además leer resúmenes: el enlace los enseña, así que quien no puede
    verlos tampoco puede publicarlos.
    """
    if not has_module_read(user, "digests"):
        raise HTTPException(status_code=403, detail="Necesitas acceso de lectura a resúmenes para compartirlos")
    await _client_or_404(db, client_id, lock=True)
    _link, token = await links.create_link(db, client_id, user.id)
    await db.commit()
    return {**await _status(db, client_id), "path": f"/c/{token}"}


@router.delete("/api/clients/{client_id}/share-link", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("clients", write=True)),
):
    await _client_or_404(db, client_id, lock=True)
    await links.revoke_link(db, client_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/public/clients/{token}")
async def public_client_view(token: str, request: Request, response: Response,
                             db: AsyncSession = Depends(get_db)):
    """Vista pública sin login. Desconocido, revocado o mal formado → el mismo 404."""
    client_ip = request.client.host if request.client else "unknown"
    public_link_limiter.check(client_ip, max_requests=30, window_seconds=60)
    link = await links.resolve_token(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND, headers=_PUBLIC_HEADERS)
    body = await links.public_view(db, link)
    await links.touch_view(db, link)
    response.headers.update(_PUBLIC_HEADERS)
    return body
