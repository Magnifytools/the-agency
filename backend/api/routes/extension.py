"""Chrome extension update endpoint."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException
from fastapi.responses import Response, FileResponse

from backend.api.deps import get_current_user
from backend.core.rate_limiter import _SlidingWindowLimiter
from backend.db.models import User
from backend.services.extension_package import (
    ExtensionPackageUnavailable, build_package, package_filename, read_release_notes, read_version,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extension"])
_ext_limiter = _SlidingWindowLimiter(
    prefix="rate:ext",
    detail_fn=lambda _m, _w: "Too many requests",
)

_MANIFEST = Path(__file__).resolve().parents[3] / "chrome-extension" / "manifest.json"
_CRX = Path(__file__).resolve().parents[3] / "chrome-extension" / "dist" / "agency-manager.crx"
_EXT_ID_FILE = Path(__file__).resolve().parents[3] / "chrome-extension" / "dist" / "extension-id.txt"

_CRX_URL = "https://agency.magnifytools.com/extension/agency-manager.crx"


def _get_version() -> str:
    try:
        return json.loads(_MANIFEST.read_text())["version"]
    except Exception:
        return "1.0.0"


def _get_extension_id() -> str | None:
    try:
        return _EXT_ID_FILE.read_text().strip() or None
    except Exception:
        return None


@router.get("/extension/update.xml", include_in_schema=False)
async def extension_update_xml(request: Request):
    """Chrome extension auto-update manifest."""
    client_ip = request.client.host if request.client else "unknown"
    _ext_limiter.check(f"xml:{client_ip}", max_requests=10, window_seconds=60)
    ext_id = _get_extension_id()
    if not ext_id:
        raise HTTPException(status_code=404, detail="Extension ID not configured")

    version = _get_version()
    xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>
  <app appid='{ext_id}'>
    <updatecheck status='ok'
                 version='{version}'
                 prodversionmin='88.0.0.0'
                 codebase='{_CRX_URL}' />
  </app>
</gupdate>"""
    return Response(content=xml, media_type="application/xml")


@router.get("/extension/agency-manager.crx", include_in_schema=False)
async def extension_crx(request: Request):
    """Serve the packaged Chrome extension."""
    client_ip = request.client.host if request.client else "unknown"
    _ext_limiter.check(f"crx:{client_ip}", max_requests=5, window_seconds=60)
    if not _CRX.is_file():
        raise HTTPException(status_code=404, detail="CRX not built yet")
    return FileResponse(
        str(_CRX),
        media_type="application/x-chrome-extension",
        filename="agency-manager.crx",
    )


# ── Descarga para "Cargar descomprimida" (Ajustes → Extensión de Chrome) ──
# Requiere sesión: la extensión es una herramienta interna del equipo.
DOWNLOAD_PATH = "/api/extension/download"


@router.get("/api/extension")
async def extension_info(_: User = Depends(get_current_user)):
    """Versión que se descargaría ahora, cuándo salió y qué trae, para enseñarlo
    junto al botón. Las novedades son las de esa versión y las dos anteriores."""
    try:
        version = read_version()
    except ExtensionPackageUnavailable:
        raise HTTPException(status_code=503, detail="La extensión no está disponible en este despliegue")
    try:
        releases = read_release_notes()
    except (OSError, ValueError, KeyError, TypeError):
        logger.error("novedades.json de la extensión mal formado")
        releases = []
    current = next((r for r in releases if r.version == version), None)
    return {
        "version": version, "filename": package_filename(version), "download_url": DOWNLOAD_PATH,
        "released_on": current.date.isoformat() if current else None,
        "releases": [
            {"version": r.version, "date": r.date.isoformat(), "changes": list(r.changes)} for r in releases[:3]
        ],
    }


@router.get(DOWNLOAD_PATH)
async def extension_download(_: User = Depends(get_current_user)):
    """Zip de la versión desplegada, armado desde los ficheros de la imagen."""
    try:
        package = build_package()
    except ExtensionPackageUnavailable as exc:
        logger.error("Extension package unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="La extensión no está disponible en este despliegue")
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "Cache-Control": "no-store",
        },
    )
