"""Webs: ajustes de la vigilancia de cambios por cliente (captura y calendario).

Viven en ``client_web_settings`` junto al Slack del cliente, pero aquí no se
toca el webhook (eso es ``web_uptime.py``, sólo admin). Leer = módulo ``web``;
cambiar = escritura en ``web``. Cada valor guardado puede volver a NULL, que
significa "el default del código" (``services/web/capture_defaults.py``): la
respuesta trae el valor guardado y el efectivo, para que se vea de dónde sale.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import ClientWebSettings, User
from backend.schemas.web import CalendarSettingsUpdate, CaptureSettingsUpdate
from backend.services.web import capture_defaults as defaults
from backend.services.web.calendario import festivos_nacionales
from backend.services.web.sweep import effective_settings, slack_state, sweep_start_time
from backend.services.web.uptime_views import iso

router = APIRouter(tags=["web"])

MODULE = "web"
_CAPTURE_FIELDS = ("default_content_selector", "default_ignore_selectors", "default_ignore_regexes",
                   "max_concurrency", "request_timeout_s", "crawl_delay_ms", "digest_min_severity")


def _view(web: ClientWebSettings | None) -> dict:
    cfg = effective_settings(web)
    stored = {name: getattr(web, name, None) if web is not None else None for name in (
        *_CAPTURE_FIELDS, "sweep_weekdays", "sweep_skip_dates", "sweep_summary_to_slack")}
    return {
        "enabled": settings.WEB_SWEEP_ENABLED,
        "sweep_local_time": sweep_start_time().strftime("%H:%M"),
        # Lo guardado (null = default del código) y lo que de verdad se usa.
        "stored": stored,
        "effective": {
            "default_content_selector": cfg.content_selector,
            "default_ignore_selectors": list(cfg.ignore_selectors),
            "default_ignore_regexes": list(cfg.ignore_regexes),
            "max_concurrency": cfg.max_concurrency,
            "request_timeout_s": cfg.request_timeout_s,
            "crawl_delay_ms": cfg.crawl_delay_ms,
            "digest_min_severity": cfg.digest_min_severity,
            "sweep_weekdays": list(cfg.sweep_weekdays),
            "sweep_skip_dates": list(cfg.sweep_skip_dates),
            "sweep_summary_to_slack": cfg.sweep_summary_to_slack,
        },
        "code_defaults": {
            "default_ignore_selectors": list(defaults.DEFAULT_IGNORE_SELECTORS),
            "default_ignore_regexes": list(defaults.DEFAULT_IGNORE_REGEXES),
            "max_concurrency": defaults.DEFAULT_MAX_CONCURRENCY,
            "request_timeout_s": defaults.DEFAULT_REQUEST_TIMEOUT_S,
            "crawl_delay_ms": defaults.DEFAULT_CRAWL_DELAY_MS,
            "digest_min_severity": defaults.DEFAULT_DIGEST_MIN_SEVERITY,
            "sweep_weekdays": list(defaults.DEFAULT_SWEEP_WEEKDAYS),
            "sweep_summary_to_slack": defaults.DEFAULT_SWEEP_SUMMARY_TO_SLACK,
        },
        # "Configurado" y "activo" no son lo mismo (lección 0nonies de Vigil).
        "slack": slack_state(web),
        "updated_at": iso(web.updated_at) if web is not None else None,
    }


async def _settings_row(db: AsyncSession, client_id: int) -> ClientWebSettings:
    web = await db.get(ClientWebSettings, client_id)
    if web is None:
        web = ClientWebSettings(client_id=client_id, slack_enabled=False, downtime_to_slack=True)
        db.add(web)
    return web


@router.get("/api/clients/{client_id}/web/settings/changes")
async def get_change_settings(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    await get_client_or_404(client_id, db)
    return _view(await db.get(ClientWebSettings, client_id))


@router.put("/api/clients/{client_id}/web/settings/capture")
async def put_capture_settings(
    client_id: int,
    body: CaptureSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Poda, sección y ritmo de las peticiones. Antes de añadir un selector de
    poda, mide cuántas palabras se lleva ("Probar esta configuración"): uno mal
    elegido no hace ruido, hace SILENCIO (lección 0quater de Vigil)."""
    await get_client_or_404(client_id, db)
    web = await _settings_row(db, client_id)
    for name in _CAPTURE_FIELDS:
        if name in body.model_fields_set:
            setattr(web, name, getattr(body, name))
    web.updated_by, web.updated_at = user.id, datetime.now(UTC)
    await db.commit()
    return _view(web)


@router.put("/api/clients/{client_id}/web/settings/calendar")
async def put_calendar_settings(
    client_id: int,
    body: CalendarSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Qué días corre el barrido automático y si se manda el resumen a Slack.
    "Comprobar todas" a mano no mira el calendario."""
    await get_client_or_404(client_id, db)
    web = await _settings_row(db, client_id)
    web.sweep_weekdays = body.sweep_weekdays
    web.sweep_skip_dates = body.sweep_skip_dates
    web.sweep_summary_to_slack = body.sweep_summary_to_slack
    web.updated_by, web.updated_at = user.id, datetime.now(UTC)
    await db.commit()
    return _view(web)


@router.get("/api/web/settings/holidays")
async def national_holidays(
    year: int = Query(..., alias="anio"),
    _user: User = Depends(require_module(MODULE)),
):
    """Festivos nacionales de España de un año para precargarlos en el
    calendario. Se calculan (Viernes Santo incluido): una lista a mano caduca
    en silencio. Los autonómicos y locales los añade cada uno."""
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=422, detail="Año fuera de rango")
    return {"year": year, "holidays": festivos_nacionales(year)}
