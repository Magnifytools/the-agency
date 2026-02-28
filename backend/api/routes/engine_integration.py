"""Proxy endpoints to fetch data from The Engine (Magnify)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
import httpx

from backend.config import settings
from backend.api.deps import get_current_user, require_admin
from backend.db.models import User

router = APIRouter(prefix="/api/engine", tags=["engine-integration"])


def _engine_headers() -> dict[str, str]:
    if not settings.ENGINE_SERVICE_KEY:
        raise HTTPException(status_code=503, detail="ENGINE_SERVICE_KEY not configured")
    return {"X-Service-Key": settings.ENGINE_SERVICE_KEY}


def _engine_url(path: str) -> str:
    base = (settings.ENGINE_API_URL or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="ENGINE_API_URL not configured")
    return f"{base}/api/integration{path}"


@router.get("/projects")
async def list_engine_projects(_: User = Depends(get_current_user)):
    """Proxy: list all Engine projects."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_engine_url("/projects"), headers=_engine_headers())
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Error fetching Engine projects")
    return resp.json()


@router.get("/projects/{project_id}/metrics")
async def get_engine_project_metrics(project_id: int, _: User = Depends(get_current_user)):
    """Proxy: get SEO metrics for an Engine project."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            _engine_url(f"/projects/{project_id}/metrics"),
            headers=_engine_headers(),
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Error fetching Engine metrics")
    return resp.json()


@router.post("/sync")
async def trigger_engine_sync(_: User = Depends(require_admin)):
    """Admin-only: manually trigger Engine metrics sync for all linked clients."""
    from backend.services.engine_sync_service import sync_engine_metrics
    return await sync_engine_metrics()
