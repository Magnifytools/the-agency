"""Aviso de que hay una versión nueva de la extensión de Chrome.

- **En la extensión**: ``GET /api/communication-schedules/extension-upcoming``
  lo consultan TODAS las versiones cada minuto y enseñan cada entrada como aviso
  de Chrome. Si la petición no trae ``X-Agency-Extension-Version`` (antes de la
  2.4.0 no se mandaba) o trae una versión anterior a la desplegada, se añade una
  entrada "Hay una versión nueva". La extensión la enseña una sola vez por
  instalación: su clave lleva la versión.
- **En The Agency**: un aviso en la campana (Actividad) para cada persona activa,
  una vez por versión (job ``extension_release``, al arrancar y a diario).

La versión "nueva" es la del ``manifest.json`` desplegado, la misma que se
descarga desde Ajustes → Extensión de Chrome.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Notification, User
from backend.services.extension_package import (
    ExtensionPackageUnavailable, Release, read_release_notes, read_version,
)

logger = logging.getLogger(__name__)

EXTENSION_VERSION_HEADER = "X-Agency-Extension-Version"
SETTINGS_LINK = "/settings#extension"
EXTENSION_RELEASE = "extension_release"


def _parse(version: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in (version or "").strip().split("."))
    except ValueError:
        return None


def is_outdated(installed: str | None, latest: str) -> bool:
    """Sin versión (extensiones de antes de la 2.4.0) o ilegible cuenta como antigua."""
    current, newest = _parse(installed), _parse(latest)
    if newest is None:
        return False
    return current is None or current < newest


def latest_release() -> tuple[str, Release | None] | None:
    try:
        version = read_version()
    except ExtensionPackageUnavailable:
        return None
    try:
        notes = read_release_notes()
    except (OSError, ValueError, KeyError, TypeError):
        notes = []
    return version, next((release for release in notes if release.version == version), None)


def _summary(release: Release | None) -> str:
    return release.changes[0] if release and release.changes else ""


def update_notice(installed: str | None) -> dict | None:
    """La entrada para ``extension-upcoming`` si la extensión que pregunta es antigua."""
    latest = latest_release()
    if latest is None or not is_outdated(installed, latest[0]):
        return None
    version, release = latest
    summary = _summary(release)
    return {
        # La clave lleva la versión: un aviso por instalación y versión.
        "occurrence_id": f"extension-update-{version}",
        "title": f"Hay una versión nueva de la extensión ({version})",
        "content": "Descárgala en The Agency → Ajustes → Extensión de Chrome."
                   + (f" Novedad: {summary}" if summary else ""),
        # Sin hora: la extensión enseña sólo el texto.
        "start_time": None,
        "expires_at": None,
        "minutes_until": 0,
    }


async def notify_release(db: AsyncSession) -> int:
    """Un aviso en la campana por persona activa y versión. Idempotente (``dedupe_key``)."""
    latest = latest_release()
    if latest is None:
        return 0
    version, release = latest
    user_ids = (await db.execute(select(User.id).where(User.is_active.is_(True)))).scalars().all()
    if not user_ids:
        return 0
    summary = _summary(release)
    result = await db.execute(
        insert(Notification)
        .values([
            {
                "user_id": user_id, "type": EXTENSION_RELEASE,
                "title": f"Nueva versión de la extensión de Chrome: {version}",
                "message": (summary + " " if summary else "") + "Descárgala desde Ajustes → Extensión de Chrome.",
                "link_url": SETTINGS_LINK,
                "dedupe_key": f"{EXTENSION_RELEASE}:{version}",
            }
            for user_id in user_ids
        ])
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return len(result.all())
