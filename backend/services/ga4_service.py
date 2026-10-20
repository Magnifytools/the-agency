"""GA4 propio: sesiones, eventos clave (conversiones) y tráfico desde asistentes de IA.

Usa las mismas cuentas de Google que Search Console (``gsc_connection``) con el
permiso de lectura de Analytics. Cada pasada mira qué cuenta ve cada propiedad
(Admin API) y lee sus totales diarios (Data API), guardándolos en ``ga4_daily``.
Las cifras que ven el cliente y el equipo salen de esa tabla y se pintan con
código; la IA no las redacta.

Una cuenta conectada antes de pedir el permiso de Analytics responde
``missing_scope``: se apunta en la propiedad y la cuenta NO se marca para
reconectar, porque para Search Console sigue sirviendo.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.config import settings
from backend.core.security import decrypt_vault_secret
from backend.db.models import Client, ClientStatus, Ga4Daily, Ga4PropertySync, GscConnection
from backend.services.gsc_service import SCOPES, GscAuthError, _mark_reconnect, _shift_month
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

# 16 meses la primera vez, como Search Console; luego se reimporta la última
# semana porque GA4 sigue procesando datos de días recientes.
BACKFILL_DAYS = 486
TAIL_DAYS = 7
# Un mes cuenta como cerrado en GA4 cuando se ha importado al menos estos días
# después de su último día (procesamiento de Google).
SETTLE_DAYS = 3

# Asistentes de IA que mandan tráfico con referente reconocible (sessionSource).
AI_SOURCES = (
    "chatgpt.com", "chat.openai.com", "openai.com", "perplexity.ai", "gemini.google.com",
    "bard.google.com", "copilot.microsoft.com", "claude.ai", "you.com", "poe.com",
    "chat.deepseek.com", "deepseek.com", "meta.ai", "grok.com", "chat.mistral.ai",
)


class Ga4Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Ga4Row:
    date: date
    sessions: int
    key_events: float
    ai_sessions: int
    ai_key_events: float


def configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def normalize_property(value: str | None) -> str | None:
    """'properties/123', ' 123 ' → '123'. Cualquier otra cosa no es una propiedad."""
    if not value:
        return None
    match = re.fullmatch(r"\s*(?:properties/)?(\d{4,20})\s*", value)
    return match.group(1) if match else None


def is_ai_source(source: str | None) -> bool:
    source = (source or "").lower().strip()
    return any(source == s or source.endswith("." + s) for s in AI_SOURCES)


# ── API de Google ────────────────────────────────────────────────────


def _credentials(encrypted_refresh_token: str):
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=decrypt_vault_secret(encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )


def _translate(exc: Exception) -> Exception:
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    if isinstance(exc, RefreshError):
        return GscAuthError(str(exc))
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        text = str(exc).lower()
        if status == 401:
            return GscAuthError("unauthorized")
        if status == 403 and ("scope" in text or "insufficient" in text):
            return Ga4Error("missing_scope")
        if status == 403:
            return Ga4Error("no_access")
        if status == 404:
            return Ga4Error("not_found")
        if status == 429:
            return Ga4Error("rate_limited")
    return Ga4Error("api_error")


def _list_properties_sync(encrypted_refresh_token: str) -> list[str]:
    from googleapiclient.discovery import build

    try:
        admin = build("analyticsadmin", "v1beta", credentials=_credentials(encrypted_refresh_token),
                      cache_discovery=False)
        out, token = [], None
        while True:
            page = admin.accountSummaries().list(pageSize=200, pageToken=token).execute()
            for account in page.get("accountSummaries", []):
                for prop in account.get("propertySummaries", []):
                    pid = normalize_property(prop.get("property"))
                    if pid:
                        out.append(pid)
            token = page.get("nextPageToken")
            if not token:
                return out
    except Exception as exc:  # noqa: BLE001 — se traduce a un error con código
        raise _translate(exc) from exc


def _query_daily_sync(encrypted_refresh_token: str, property_id: str, start: date, end: date) -> list[Ga4Row]:
    from googleapiclient.discovery import build

    body = {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [{"name": "date"}, {"name": "sessionSource"}],
        "metrics": [{"name": "sessions"}, {"name": "keyEvents"}],
        "limit": 100000,
    }
    try:
        data = build("analyticsdata", "v1beta", credentials=_credentials(encrypted_refresh_token),
                     cache_discovery=False)
        result = data.properties().runReport(property=f"properties/{property_id}", body=body).execute()
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return aggregate_rows(result.get("rows", []))


def aggregate_rows(rows: list[dict]) -> list[Ga4Row]:
    """Filas (fecha, fuente) de la Data API → un total por día, separando la IA."""
    days: dict[date, list[float]] = {}
    for row in rows:
        dims = [d.get("value") for d in row.get("dimensionValues", [])]
        mets = [m.get("value") for m in row.get("metricValues", [])]
        day = datetime.strptime(dims[0], "%Y%m%d").date()
        sessions, key_events = int(float(mets[0] or 0)), float(mets[1] or 0)
        acc = days.setdefault(day, [0, 0.0, 0, 0.0])
        acc[0] += sessions
        acc[1] += key_events
        if is_ai_source(dims[1] if len(dims) > 1 else None):
            acc[2] += sessions
            acc[3] += key_events
    return [Ga4Row(d, int(v[0]), round(v[1], 2), int(v[2]), round(v[3], 2)) for d, v in sorted(days.items())]


async def list_properties(encrypted_refresh_token: str) -> list[str]:
    return await asyncio.to_thread(_list_properties_sync, encrypted_refresh_token)


async def query_daily(encrypted_refresh_token: str, property_id: str, start: date, end: date) -> list[Ga4Row]:
    return await asyncio.to_thread(_query_daily_sync, encrypted_refresh_token, property_id, start, end)


# ── Importación ──────────────────────────────────────────────────────


async def tracked_properties(db) -> list[str]:
    rows = (await db.scalars(
        select(Client.ga4_property_id).where(Client.status == ClientStatus.active,
                                             Client.ga4_property_id.isnot(None))
    )).all()
    return sorted({p for p in (normalize_property(r) for r in rows) if p})


async def _record_state(db, property_id: str, *, error_code: str | None, connection_id: int | None,
                        backfilled: bool = False, last_data_date: date | None = None) -> None:
    state = await db.get(Ga4PropertySync, property_id)
    if state is None:
        state = Ga4PropertySync(property_id=property_id)
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


async def sync_property(db, token: str, property_id: str, *, connection_id: int | None,
                        fetch=query_daily, today: date | None = None) -> int:
    end = (today or business_today()) - timedelta(days=1)
    state = await db.get(Ga4PropertySync, property_id)
    if state is None or state.backfilled_at is None:
        start, backfill = end - timedelta(days=BACKFILL_DAYS), True
    else:
        anchor = state.last_data_date or end
        start, backfill = min(anchor, end) - timedelta(days=TAIL_DAYS), False
    await db.commit()

    try:
        rows = await fetch(token, property_id, start, end)
    except Ga4Error as exc:
        await _record_state(db, property_id, error_code=exc.code, connection_id=connection_id)
        raise

    if rows:
        stmt = pg_insert(Ga4Daily).values([
            {"property_id": property_id, "date": r.date, "sessions": r.sessions, "key_events": r.key_events,
             "ai_sessions": r.ai_sessions, "ai_key_events": r.ai_key_events}
            for r in rows
        ])
        await db.execute(stmt.on_conflict_do_update(
            index_elements=[Ga4Daily.property_id, Ga4Daily.date],
            set_={k: getattr(stmt.excluded, k) for k in ("sessions", "key_events", "ai_sessions", "ai_key_events")},
        ))
    await _record_state(db, property_id, error_code=None, connection_id=connection_id, backfilled=backfill,
                        last_data_date=max((r.date for r in rows), default=None))
    return len(rows)


async def sync_all(session_factory, *, fetch=query_daily, list_fn=list_properties, today: date | None = None) -> dict:
    async with session_factory() as db:
        connections = [(c.id, c.refresh_token) for c in (await db.scalars(
            select(GscConnection).where(GscConnection.status == "connected").order_by(GscConnection.id)
        )).all()]
        properties = await tracked_properties(db)
    if not connections:
        return {"status": "not_connected", "synced": 0, "failed": 0}

    access: dict[str, int] = {}
    scope_missing: list[int] = []
    for connection_id, token in connections:
        try:
            for pid in await list_fn(token):
                access.setdefault(pid, connection_id)
        except GscAuthError:
            await _mark_reconnect(session_factory, connection_id)
        except Ga4Error as exc:
            if exc.code == "missing_scope":
                scope_missing.append(connection_id)
            logger.warning("GA4: no se pudo listar la cuenta %s (%s)", connection_id, exc.code)
    tokens = dict(connections)

    synced = failed = 0
    for pid in properties:
        connection_id = access.get(pid)
        if connection_id is None:
            # Sin cuenta que la vea: si alguna cuenta no tiene aún el permiso de
            # Analytics, ése es el motivo más probable y es el que se enseña.
            code = "missing_scope" if scope_missing else "no_access"
            async with session_factory() as db:
                await _record_state(db, pid, error_code=code, connection_id=None)
            failed += 1
            continue
        try:
            async with session_factory() as db:
                await sync_property(db, tokens[connection_id], pid, connection_id=connection_id,
                                    fetch=fetch, today=today)
            synced += 1
        except GscAuthError:
            await _mark_reconnect(session_factory, connection_id)
            failed += 1
        except Ga4Error as exc:
            failed += 1
            logger.warning("GA4: fallo al importar %s (%s)", pid, exc.code)
    return {"status": "ok", "synced": synced, "failed": failed}


# ── Lectura: ficha y resumen mensual ─────────────────────────────────


async def _totals(db, property_id: str, start: date, end: date) -> dict | None:
    row = (await db.execute(select(
        func.count(Ga4Daily.date), func.sum(Ga4Daily.sessions), func.sum(Ga4Daily.key_events),
        func.sum(Ga4Daily.ai_sessions), func.sum(Ga4Daily.ai_key_events),
    ).where(Ga4Daily.property_id == property_id, Ga4Daily.date >= start, Ga4Daily.date <= end))).one()
    if not row[0]:
        return None
    return {"start": start.isoformat(), "end": end.isoformat(), "days": int(row[0]),
            "sessions": int(row[1] or 0), "key_events": round(float(row[2] or 0), 1),
            "ai_sessions": int(row[3] or 0), "ai_key_events": round(float(row[4] or 0), 1)}


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def _vs(current: dict, other: dict | None) -> dict | None:
    if not other:
        return None
    return {k + "_pct": _pct(current[k], other[k]) for k in ("sessions", "key_events", "ai_sessions")}


async def windows(db, property_ids: set[str], *, days: int = 28) -> dict[str, dict]:
    """Últimos ``days`` días con datos frente a los ``days`` anteriores, por propiedad (para la ficha)."""
    out = {}
    for pid in property_ids:
        state = await db.get(Ga4PropertySync, pid)
        if state is None or state.last_data_date is None:
            continue
        end = state.last_data_date
        current = await _totals(db, pid, end - timedelta(days=days - 1), end)
        if current is None:
            continue
        previous = await _totals(db, pid, end - timedelta(days=2 * days - 1), end - timedelta(days=days))
        out[pid] = {"current": current, "previous": previous, "vs_previous": _vs(current, previous),
                    "as_of": end.isoformat()}
    return out


async def month_summary(db, property_id: str | None, period_start: date, period_end: date) -> dict:
    """Bloque GA4 de un mes natural cerrado. Siempre devuelve un ``status``."""
    pid = normalize_property(property_id)
    if pid is None:
        return {"status": "no_property"}
    state = await db.get(Ga4PropertySync, pid)
    if state is None or state.backfilled_at is None:
        return {"status": "not_synced", "property_id": pid, "error_code": state.error_code if state else None}
    settled = state.last_synced_at and state.last_synced_at.date() >= period_end + timedelta(days=SETTLE_DAYS)
    if state.last_data_date is None or state.last_data_date < period_end or not settled:
        return {"status": "incomplete", "property_id": pid,
                "last_data_date": state.last_data_date.isoformat() if state.last_data_date else None}
    month = await _totals(db, pid, period_start, period_end)
    if month is None:
        return {"status": "no_data", "property_id": pid}
    previous = await _totals(db, pid, *_shift_month(period_start, -1))
    year_ago = await _totals(db, pid, *_shift_month(period_start, -12))
    return {"status": "ok", "property_id": pid, "month": month, "previous": previous, "year_ago": year_ago,
            "vs_previous": _vs(month, previous), "vs_year_ago": _vs(month, year_ago)}
