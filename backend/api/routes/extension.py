"""Chrome extension update endpoint."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response, FileResponse, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extension"])

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
async def extension_update_xml():
    """Chrome extension auto-update manifest."""
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
async def extension_crx():
    """Serve the packaged Chrome extension."""
    if not _CRX.is_file():
        raise HTTPException(status_code=404, detail="CRX not built yet")
    return FileResponse(
        str(_CRX),
        media_type="application/x-chrome-extension",
        filename="agency-manager.crx",
    )
