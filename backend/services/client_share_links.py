"""Enlace de sólo lectura para el cliente (fase 3 Agency 2.0).

El cliente ve SOLO dos cosas: los resúmenes que se le entregaron (entrega externa
confirmada, la misma regla que ``report_unsent``) y sus clics/impresiones de
Google por mes desde ``gsc_daily``. Nada de tareas, borradores ni notas internas.

El token nunca se guarda: sólo su SHA-256. Quien tiene la base de datos no puede
reconstruir el enlace, y el enlace completo se enseña una única vez al crearlo.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client,
    ClientShareLink,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    GscDaily,
    GscSiteSync,
    WeeklyDigest,
)
from backend.schemas.digest import DigestContent
from backend.services.digest_periods import format_digest_period
from backend.services.digest_renderer import render_email
from backend.services.gsc_service import normalize_site_url
from backend.services.incident_report_conditions import delivery_is_confirmed

TRAFFIC_MONTHS = 16
# Una escritura por visita sería una escritura por cada recarga del cliente.
VIEW_TOUCH_INTERVAL = timedelta(hours=1)
# secrets.token_urlsafe(32) → 43 caracteres base64url.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def active_link(db: AsyncSession, client_id: int) -> ClientShareLink | None:
    return await db.scalar(select(ClientShareLink).where(
        ClientShareLink.client_id == client_id, ClientShareLink.revoked_at.is_(None),
    ))


async def create_link(db: AsyncSession, client_id: int, user_id: int) -> tuple[ClientShareLink, str]:
    """Revoca el enlace activo (si lo hay) y crea otro. Devuelve el token en claro."""
    now = datetime.now(UTC)
    await revoke_link(db, client_id, now=now)
    token = new_token()
    link = ClientShareLink(client_id=client_id, token_hash=hash_token(token),
                           created_by=user_id, created_at=now)
    db.add(link)
    await db.flush()
    return link, token


async def revoke_link(db: AsyncSession, client_id: int, *, now: datetime | None = None) -> bool:
    result = await db.execute(
        update(ClientShareLink)
        .where(ClientShareLink.client_id == client_id, ClientShareLink.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )
    return bool(result.rowcount)


async def resolve_token(db: AsyncSession, token: str) -> ClientShareLink | None:
    """El enlace activo de ese token, o None (desconocido, revocado o mal formado)."""
    if not _TOKEN_RE.fullmatch(token):
        return None
    digest = hash_token(token)
    link = await db.scalar(select(ClientShareLink).where(
        ClientShareLink.token_hash == digest, ClientShareLink.revoked_at.is_(None),
    ))
    if link is None or not hmac.compare_digest(link.token_hash, digest):
        return None
    return link


async def touch_view(db: AsyncSession, link: ClientShareLink) -> None:
    now = datetime.now(UTC)
    if link.last_viewed_at is None or now - link.last_viewed_at >= VIEW_TOUCH_INTERVAL:
        await db.execute(update(ClientShareLink).where(ClientShareLink.id == link.id)
                         .values(last_viewed_at=now))
        await db.commit()


async def _delivered_versions(db: AsyncSession, client_id: int) -> list[tuple[WeeklyDigest, DigestContent, datetime | None]]:
    """Resúmenes con entrega externa confirmada, uno por periodo (la última versión entregada)."""
    confirmed_at = (
        select(func.max(DigestExternalDeliveryEvent.created_at))
        .where(DigestExternalDeliveryEvent.digest_id == WeeklyDigest.id,
               DigestExternalDeliveryEvent.action == ExternalDeliveryAction.confirmed)
        .correlate(WeeklyDigest)
        .scalar_subquery()
    )
    rows = (await db.execute(
        select(WeeklyDigest, confirmed_at.label("delivered_at"))
        .where(WeeklyDigest.client_id == client_id, WeeklyDigest.content.isnot(None),
               delivery_is_confirmed())
        .order_by(WeeklyDigest.period_end.desc(), confirmed_at.desc(), WeeklyDigest.id.desc())
    )).all()
    seen: set[tuple[date, date]] = set()
    out: list[tuple[WeeklyDigest, DigestContent, datetime | None]] = []
    for digest, delivered_at in rows:
        period = (digest.period_start, digest.period_end)
        if period in seen:
            continue
        try:
            content = DigestContent(**digest.content)
        except Exception:
            continue
        seen.add(period)
        out.append((digest, content, delivered_at))
    return out


async def delivered_digests(db: AsyncSession, client_id: int) -> list[dict]:
    """Lo que enseña la página pública: la versión entregada de cada periodo, ya pintada."""
    return [{
        "id": digest.id,
        "period_start": digest.period_start.isoformat(),
        "period_end": digest.period_end.isoformat(),
        "period_label": format_digest_period(digest.period_start, digest.period_end),
        "delivered_at": delivered_at.isoformat() if delivered_at else None,
        "html": render_email(content, tone=digest.tone, period_start=digest.period_start,
                             period_end=digest.period_end,
                             seo=(digest.raw_context or {}).get("seo"),
                             ga4=(digest.raw_context or {}).get("ga4")),
    } for digest, content, delivered_at in await _delivered_versions(db, client_id)]


async def delivered_digest(db: AsyncSession, client_id: int, digest_id: int) -> WeeklyDigest | None:
    """La versión entregada con ese id, sólo si es la que enseña la página pública."""
    return next((digest for digest, _content, _at in await _delivered_versions(db, client_id)
                 if digest.id == digest_id), None)


def _month_start(day: date, back: int = 0) -> date:
    index = day.year * 12 + day.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


async def monthly_traffic(db: AsyncSession, gsc_url: str | None) -> dict | None:
    """Clics, impresiones y posición por mes natural CERRADO (hasta 16 meses).

    Un mes sólo cuenta si hay datos finales hasta su último día; el mes en curso
    nunca sale a medias. Clics e impresiones se suman, la posición se pondera por
    impresiones.
    """
    site = normalize_site_url(gsc_url)
    if site is None:
        return None
    last_data_date = await db.scalar(select(GscSiteSync.last_data_date).where(GscSiteSync.site_url == site))
    if last_data_date is None:
        return None
    # Último mes completo: el de last_data_date si es su último día, si no el anterior.
    complete_through = _month_start(last_data_date + timedelta(days=1)) - timedelta(days=1)
    first = _month_start(complete_through, TRAFFIC_MONTHS - 1)
    month = func.to_char(GscDaily.date, "YYYY-MM")
    rows = (await db.execute(
        select(month.label("month"), func.sum(GscDaily.clicks), func.sum(GscDaily.impressions),
               func.sum(GscDaily.position * GscDaily.impressions))
        .where(GscDaily.site_url == site, GscDaily.date >= first, GscDaily.date <= complete_through)
        .group_by(month).order_by(month)
    )).all()
    months = [{
        "month": m,
        "clicks": int(clicks),
        "impressions": int(impressions),
        "position": round(float(weighted) / impressions, 1) if impressions else None,
    } for m, clicks, impressions, weighted in rows]
    if not months:
        return None
    return {"months": months, "complete_through": complete_through.isoformat()}


async def public_view(db: AsyncSession, link: ClientShareLink) -> dict:
    name, gsc_url = (await db.execute(
        select(Client.name, Client.gsc_url).where(Client.id == link.client_id)
    )).one()
    return {
        "client_name": name,
        "traffic": await monthly_traffic(db, gsc_url),
        "digests": await delivered_digests(db, link.client_id),
    }
