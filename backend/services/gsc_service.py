"""Search Console propio: conexión, importación diaria y resumen mensual.

La agencia conecta UNA cuenta de Google con acceso a las propiedades de sus
clientes. Cada día se importan los totales diarios finales de cada propiedad
(`Client.gsc_url`) y se guardan en `gsc_daily`, así que el histórico no se
pierde a los 16 meses como en Search Console.

Reglas de las cifras (globales): clics e impresiones se suman en la ventana;
la posición es la media ponderada por impresiones. Sólo se usan datos
finales (`dataState=final`): GSC consolida con 2-3 días de retraso, y un mes
sólo cuenta como completo cuando hay datos finales hasta su último día.
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.config import settings
from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.models import Client, ClientStatus, GscConnection, GscDaily, GscSiteSync
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly", "openid", "email"]
# 16 meses: lo máximo que guarda Search Console.
BACKFILL_DAYS = 486
# GSC revisa los últimos días: se vuelven a pedir en cada pasada.
TAIL_DAYS = 7


class GscAuthError(Exception):
    """El token ya no vale: hay que volver a conectar la cuenta."""


class GscSiteError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DailyRow:
    date: date
    clicks: int
    impressions: int
    position: float


def configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def normalize_site_url(value: str | None) -> str | None:
    """Propiedad tal y como la espera la API: 'sc-domain:x.com' o URL con barra final."""
    if not value or not value.strip():
        return None
    site = value.strip()
    if site.startswith("sc-domain:"):
        return site
    if site.startswith(("http://", "https://")) and not site.endswith("/"):
        site += "/"
    return site


# ── OAuth ─────────────────────────────────────────────────────────────


def get_auth_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GSC_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        # select_account: para añadir una cuenta distinta a la que ya tiene sesión.
        "prompt": "consent select_account",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"


def _email_from_id_token(id_token: str | None) -> str | None:
    # Recibido directamente del endpoint de tokens de Google por TLS: OIDC
    # permite leerlo sin validar la firma en este caso.
    if not id_token or id_token.count(".") != 2:
        return None
    payload = id_token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    email = claims.get("email")
    return email if isinstance(email, str) else None


async def exchange_code(code: str) -> tuple[str, str | None]:
    """Devuelve (refresh_token, email de la cuenta)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GSC_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        logger.warning("GSC token exchange failed (HTTP %s)", resp.status_code)
        raise ValueError("token_exchange_failed")
    data = resp.json()
    if not data.get("refresh_token"):
        raise ValueError("no_refresh_token")
    return data["refresh_token"], _email_from_id_token(data.get("id_token"))


async def save_connection(db, *, refresh_token: str, email: str | None, user_id: int) -> GscConnection:
    """Añade una cuenta o renueva la que ya estaba (misma dirección de Google)."""
    email = email.lower() if email else None
    connection = (await db.scalar(select(GscConnection).where(GscConnection.google_email == email))
                  if email else None)
    if connection is None:
        connection = GscConnection()
        db.add(connection)
    connection.refresh_token = encrypt_vault_secret(refresh_token)
    connection.google_email = email
    connection.status = "connected"
    connection.connected_by = user_id
    connection.connected_at = datetime.now(UTC)
    await db.flush()
    return connection


# ── API de Search Console ────────────────────────────────────────────


def _service(encrypted_refresh_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=decrypt_vault_secret(encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _translate(exc: Exception) -> Exception:
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    if isinstance(exc, RefreshError):
        return GscAuthError(str(exc))
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        if status == 401:
            return GscAuthError("unauthorized")
        if status == 403:
            return GscSiteError("no_access")
        if status == 404:
            return GscSiteError("not_found")
        if status == 429:
            return GscSiteError("rate_limited")
    return GscSiteError("api_error")


def _list_sites_sync(encrypted_refresh_token: str) -> list[dict]:
    try:
        result = _service(encrypted_refresh_token).sites().list().execute()
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise _translate(exc) from exc
    return [
        {"site_url": s["siteUrl"], "permission": s.get("permissionLevel")}
        for s in result.get("siteEntry", [])
        if s.get("permissionLevel") != "siteUnverifiedUser"
    ]


def _query_daily_sync(encrypted_refresh_token: str, site_url: str, start: date, end: date) -> list[DailyRow]:
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date"],
        "type": "web",
        "dataState": "final",
        "rowLimit": 25000,
    }
    try:
        result = _service(encrypted_refresh_token).searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return [
        DailyRow(
            date=date.fromisoformat(row["keys"][0]),
            clicks=int(row.get("clicks", 0)),
            impressions=int(row.get("impressions", 0)),
            position=float(row.get("position", 0.0)),
        )
        for row in result.get("rows", [])
    ]


async def list_sites(encrypted_refresh_token: str) -> list[dict]:
    return await asyncio.to_thread(_list_sites_sync, encrypted_refresh_token)


async def query_daily(encrypted_refresh_token: str, site_url: str, start: date, end: date) -> list[DailyRow]:
    return await asyncio.to_thread(_query_daily_sync, encrypted_refresh_token, site_url, start, end)


# ── Importación ──────────────────────────────────────────────────────


async def tracked_sites(db) -> list[str]:
    rows = (await db.scalars(
        select(Client.gsc_url).where(Client.status == ClientStatus.active, Client.gsc_url.isnot(None))
    )).all()
    return sorted({site for site in (normalize_site_url(r) for r in rows) if site})


async def sync_site(db, encrypted_refresh_token: str, site_url: str, *, fetch=query_daily,
                    today: date | None = None, connection_id: int | None = None) -> int:
    """Importa una propiedad. Devuelve cuántos días se han guardado.

    No mantiene transacción abierta durante la llamada a Google.
    """
    end = (today or business_today()) - timedelta(days=1)
    state = await db.get(GscSiteSync, site_url)
    if state is None or state.backfilled_at is None:
        start, backfill = end - timedelta(days=BACKFILL_DAYS), True
    else:
        anchor = state.last_data_date or end
        start, backfill = min(anchor, end) - timedelta(days=TAIL_DAYS), False
    await db.commit()

    try:
        rows = await fetch(encrypted_refresh_token, site_url, start, end)
    except GscSiteError as exc:
        await _record_state(db, site_url, error_code=exc.code, connection_id=connection_id)
        raise

    if rows:
        stmt = pg_insert(GscDaily).values([
            {"site_url": site_url, "date": r.date, "clicks": r.clicks,
             "impressions": r.impressions, "position": r.position}
            for r in rows
        ])
        await db.execute(stmt.on_conflict_do_update(
            index_elements=[GscDaily.site_url, GscDaily.date],
            set_={"clicks": stmt.excluded.clicks, "impressions": stmt.excluded.impressions,
                  "position": stmt.excluded.position},
        ))
    await _record_state(
        db, site_url, error_code=None, backfilled=backfill,
        last_data_date=max((r.date for r in rows), default=None), connection_id=connection_id,
    )
    return len(rows)


async def _record_state(db, site_url: str, *, error_code: str | None, backfilled: bool = False,
                        last_data_date: date | None = None, connection_id: int | None = None) -> None:
    state = await db.get(GscSiteSync, site_url)
    if state is None:
        state = GscSiteSync(site_url=site_url)
        db.add(state)
    now = datetime.now(UTC)
    state.last_synced_at = now
    state.error_code = error_code
    state.connection_id = connection_id
    if backfilled:
        state.backfilled_at = now
    if last_data_date and (state.last_data_date is None or last_data_date > state.last_data_date):
        state.last_data_date = last_data_date
    await db.commit()


_PERMISSION_RANK = {"siteOwner": 0, "siteFullUser": 1, "siteRestrictedUser": 2}


async def _mark_reconnect(session_factory, connection_id: int) -> None:
    async with session_factory() as db:
        connection = await db.get(GscConnection, connection_id)
        if connection is not None:
            connection.status = "reconnect_required"
            await db.commit()


async def site_access(session_factory, *, list_fn=list_sites) -> tuple[dict[str, int], list[int]]:
    """Qué cuenta conectada ve cada propiedad. Devuelve (propiedad → cuenta, cuentas caídas).

    Si varias la ven, gana la de más permiso y, a igualdad, la más antigua.
    Una cuenta que Google rechaza se marca para reconectar y no tumba a las demás.
    """
    async with session_factory() as db:
        connections = [(c.id, c.refresh_token) for c in (await db.scalars(
            select(GscConnection).where(GscConnection.status == "connected").order_by(GscConnection.id)
        )).all()]
    best: dict[str, tuple[int, int]] = {}
    failed: list[int] = []
    for connection_id, token in connections:
        try:
            sites = await list_fn(token)
        except GscAuthError:
            await _mark_reconnect(session_factory, connection_id)
            failed.append(connection_id)
            logger.warning("Search Console: la cuenta %s necesita reconectarse", connection_id)
            continue
        except GscSiteError as exc:
            logger.warning("Search Console: no se pudo listar la cuenta %s (%s)", connection_id, exc.code)
            continue
        for s in sites:
            rank = _PERMISSION_RANK.get(s.get("permission") or "", 3)
            current = best.get(s["site_url"])
            if current is None or rank < current[1]:
                best[s["site_url"]] = (connection_id, rank)
    return {site: cid for site, (cid, _) in best.items()}, failed


async def sync_all(session_factory, *, fetch=query_daily, list_fn=list_sites, today: date | None = None) -> dict:
    """Una pasada sobre todas las propiedades. Cada propiedad con la cuenta que la ve, en su sesión."""
    async with session_factory() as db:
        any_connected = await db.scalar(select(GscConnection.id).where(GscConnection.status == "connected").limit(1))
        if any_connected is None:
            has_any = await db.scalar(select(GscConnection.id).limit(1))
            return {"status": "reconnect_required" if has_any else "not_connected", "synced": 0, "failed": 0}
        sites = await tracked_sites(db)

    access, broken = await site_access(session_factory, list_fn=list_fn)
    async with session_factory() as db:
        tokens = {c.id: c.refresh_token for c in (await db.scalars(
            select(GscConnection).where(GscConnection.status == "connected")
        )).all()}

    synced = failed = 0
    for site in sites:
        connection_id = access.get(site)
        if connection_id is None or connection_id not in tokens:
            # Ninguna cuenta conectada la ve: se apunta y se sigue con las demás.
            async with session_factory() as db:
                await _record_state(db, site, error_code="no_access", connection_id=None)
            failed += 1
            continue
        try:
            async with session_factory() as db:
                await sync_site(db, tokens[connection_id], site, fetch=fetch, today=today,
                                connection_id=connection_id)
            synced += 1
        except GscAuthError:
            await _mark_reconnect(session_factory, connection_id)
            tokens.pop(connection_id, None)
            broken.append(connection_id)
            failed += 1
        except GscSiteError as exc:
            failed += 1
            logger.warning("Search Console: fallo al importar %s (%s)", site, exc.code)
    status = "reconnect_required" if broken else "ok"
    return {"status": status, "synced": synced, "failed": failed}


# ── Resumen mensual ──────────────────────────────────────────────────


def is_full_month(period_start: date, period_end: date) -> bool:
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    return period_start.day == 1 and period_end == period_start.replace(day=last_day)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(day: date, months: int) -> tuple[date, date]:
    index = day.year * 12 + (day.month - 1) + months
    return _month_bounds(index // 12, index % 12 + 1)


async def _aggregate(db, site_url: str, start: date, end: date) -> dict | None:
    row = (await db.execute(
        select(
            func.count(GscDaily.date),
            func.coalesce(func.sum(GscDaily.clicks), 0),
            func.coalesce(func.sum(GscDaily.impressions), 0),
            func.sum(GscDaily.position * GscDaily.impressions),
        ).where(GscDaily.site_url == site_url, GscDaily.date >= start, GscDaily.date <= end)
    )).one()
    days, clicks, impressions, weighted = row
    if not days:
        return None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": int(days),
        "clicks": int(clicks),
        "impressions": int(impressions),
        "ctr": round(clicks * 100 / impressions, 2) if impressions else None,
        "position": round(float(weighted) / impressions, 1) if impressions else None,
    }


def _pct(current: int | None, previous: int | None) -> float | None:
    if current is None or not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def _changes(current: dict, other: dict | None) -> dict | None:
    if other is None:
        return None
    position_delta = None
    if current["position"] is not None and other["position"] is not None:
        # Positivo = mejora (posición más baja es mejor).
        position_delta = round(other["position"] - current["position"], 1)
    ctr_delta = None
    if current["ctr"] is not None and other["ctr"] is not None:
        ctr_delta = round(current["ctr"] - other["ctr"], 2)
    return {
        "clicks_pct": _pct(current["clicks"], other["clicks"]),
        "impressions_pct": _pct(current["impressions"], other["impressions"]),
        "ctr_delta": ctr_delta,
        "position_delta": position_delta,
    }


async def month_summary(db, site_url: str | None, period_start: date, period_end: date) -> dict:
    """Bloque SEO de un mes natural cerrado. Siempre devuelve un `status`."""
    site = normalize_site_url(site_url)
    if site is None:
        return {"status": "no_property"}
    connected = await db.scalar(select(GscConnection.id).where(GscConnection.status == "connected").limit(1))
    if connected is None and await db.scalar(select(GscConnection.id).limit(1)) is None:
        return {"status": "not_connected", "site_url": site}
    state = await db.get(GscSiteSync, site)
    if state is None or state.backfilled_at is None:
        status = "not_synced" if connected is not None else "reconnect_required"
        return {"status": status, "site_url": site,
                "error_code": state.error_code if state else None}
    if state.last_data_date is None or state.last_data_date < period_end:
        return {"status": "incomplete", "site_url": site,
                "last_data_date": state.last_data_date.isoformat() if state.last_data_date else None}

    current = await _aggregate(db, site, period_start, period_end)
    if current is None:
        return {"status": "no_data", "site_url": site}
    previous = await _aggregate(db, site, *_shift_month(period_start, -1))
    year_ago = await _aggregate(db, site, *_shift_month(period_start, -12))
    return {
        "status": "ok",
        "site_url": site,
        "month": current,
        "previous": previous,
        "year_ago": year_ago,
        "vs_previous": _changes(current, previous),
        "vs_year_ago": _changes(current, year_ago),
    }
