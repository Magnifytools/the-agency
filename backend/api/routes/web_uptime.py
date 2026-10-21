"""Webs: disponibilidad (monitor de caídas). Ver ``backend/services/web/uptime.py``.

Permisos (módulo ``web``): leer = ver; escribir = gestionar URLs y "Probar
ahora". El canal de Slack de cada cliente es sólo para admins y su webhook no
sale nunca en una respuesta.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_admin, require_module
from backend.config import settings
from backend.core.rate_limiter import web_probe_limiter
from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.database import get_db
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, User, WebOutage, WebUptimeState, WebUptimeTarget,
)
from backend.schemas.web import (
    SlackSettingsResponse, SlackSettingsUpdate, UptimeTargetCreate, UptimeTargetUpdate,
)
from backend.services.web import slack as slack_service
from backend.services.web.uptime import cause_label, probe
from backend.services.web.uptime_views import daily_history, iso, outage_view, target_views, worst_status

router = APIRouter(tags=["web"])

MODULE = "web"
_PROBES_PER_MINUTE = 10


def _monitored(client: Client) -> bool:
    return client.status == ClientStatus.active and not client.is_internal


async def _target_or_404(db: AsyncSession, target_id: int, client_id: int | None = None) -> WebUptimeTarget:
    target = await db.get(WebUptimeTarget, target_id)
    if target is None or (client_id is not None and target.client_id != client_id):
        raise HTTPException(status_code=404, detail="URL no encontrada")
    return target


async def _ensure_unique(db: AsyncSession, client_id: int, url: str, exclude_id: int | None = None) -> None:
    query = select(WebUptimeTarget.id).where(WebUptimeTarget.client_id == client_id, WebUptimeTarget.url == url)
    if exclude_id is not None:
        query = query.where(WebUptimeTarget.id != exclude_id)
    if await db.scalar(query) is not None:
        raise HTTPException(status_code=409, detail="Esta URL ya está en la lista del cliente")


async def _view(db: AsyncSession, target: WebUptimeTarget) -> dict:
    return (await target_views(db, [target]))[0]


async def _reset(db: AsyncSession, target: WebUptimeTarget, now: datetime) -> None:
    """Cambiar la URL o pausarla empieza de cero: se cierra la caída abierta sin
    avisar de una "recuperación" que no ha ocurrido y el estado vuelve a desconocido."""
    await db.execute(update(WebOutage).where(
        WebOutage.target_id == target.id, WebOutage.ended_at.is_(None),
    ).values(ended_at=now, slack_recovery_status="skipped"))
    state = await db.get(WebUptimeState, target.id)
    if state is None:
        state = WebUptimeState(target_id=target.id)
        db.add(state)
    state.status, state.status_since = "unknown", now
    state.consecutive_failures = state.consecutive_successes = 0
    state.failing_since = state.blocked_since = None
    state.last_checked_at = state.last_outcome = state.last_status_code = None
    state.last_error = state.last_response_ms = None
    state.next_check_at = now


# ── Vista global ─────────────────────────────────────────────────────


@router.get("/api/web/uptime")
async def uptime_overview(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Disponibilidad de todos los clientes activos externos, lo peor primero."""
    clients = list(await db.scalars(select(Client).where(
        Client.status == ClientStatus.active, Client.is_internal.is_(False),
    ).order_by(Client.name)))
    targets = list(await db.scalars(select(WebUptimeTarget).where(
        WebUptimeTarget.client_id.in_([c.id for c in clients]),
    ).order_by(WebUptimeTarget.id))) if clients else []
    views = await target_views(db, targets, recent=False)
    by_client: dict[int, list[dict]] = {}
    for view in views:
        by_client.setdefault(view["client_id"], []).append(view)
    rows = []
    for client in clients:
        items = by_client.get(client.id, [])
        rows.append({
            "client_id": client.id,
            "client_name": client.name,
            "website": client.website,
            "status": worst_status([v["status"] for v in items if v["is_active"]]),
            "targets": items,
        })
    rank = {"down": 0, "blocked": 1, "suspect": 2, "unknown": 3, "up": 4, None: 5}
    rows.sort(key=lambda r: (rank.get(r["status"], 5), (r["client_name"] or "").lower()))
    return {"enabled": settings.UPTIME_ENABLED, "interval_seconds": settings.UPTIME_INTERVAL_SECONDS,
            "clients": rows}


# ── URLs de un cliente ───────────────────────────────────────────────


@router.get("/api/clients/{client_id}/web/uptime-targets")
async def list_targets(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    client = await get_client_or_404(client_id, db)
    targets = list(await db.scalars(select(WebUptimeTarget).where(
        WebUptimeTarget.client_id == client_id,
    ).order_by(WebUptimeTarget.id)))
    return {
        "enabled": settings.UPTIME_ENABLED,
        "monitored": _monitored(client),
        "website": client.website,
        "targets": await target_views(db, targets),
    }


@router.post("/api/clients/{client_id}/web/uptime-targets", status_code=status.HTTP_201_CREATED)
async def create_target(
    client_id: int,
    body: UptimeTargetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    await get_client_or_404(client_id, db)
    await _ensure_unique(db, client_id, body.url)
    now = datetime.now(UTC)
    target = WebUptimeTarget(client_id=client_id, url=body.url, label=body.label, is_active=True,
                             created_by=user.id, created_at=now, updated_at=now)
    db.add(target)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Esta URL ya está en la lista del cliente")
    db.add(WebUptimeState(target_id=target.id, status="unknown", status_since=now, next_check_at=now))
    await db.commit()
    return await _view(db, target)


@router.patch("/api/clients/{client_id}/web/uptime-targets/{target_id}")
async def update_target(
    client_id: int,
    target_id: int,
    body: UptimeTargetUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    target = await _target_or_404(db, target_id, client_id)
    sent = body.model_fields_set
    now = datetime.now(UTC)
    restart = False
    if "url" in sent:
        if body.url is None:
            raise HTTPException(status_code=422, detail="La URL no puede estar vacía")
        if body.url != target.url:
            await _ensure_unique(db, client_id, body.url, exclude_id=target.id)
            target.url, restart = body.url, True
    if "label" in sent:
        target.label = body.label
    if "is_active" in sent and body.is_active is not None and body.is_active != target.is_active:
        target.is_active, restart = body.is_active, True
    if sent:
        target.updated_at = now
    if restart:
        await _reset(db, target, now)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Esta URL ya está en la lista del cliente")
    return await _view(db, target)


@router.delete("/api/clients/{client_id}/web/uptime-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    client_id: int,
    target_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    """Borra la URL con su historial (sondeos y caídas). Su alerta se resuelve sola."""
    target = await _target_or_404(db, target_id, client_id)
    await db.delete(target)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/web/uptime-targets/{target_id}/probe")
async def probe_now(
    target_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Comprobación puntual. No cambia el estado ni cuenta para el % (sólo informa)."""
    web_probe_limiter.check(user.id, _PROBES_PER_MINUTE, 60)
    target = await _target_or_404(db, target_id)
    web = await db.get(ClientWebSettings, target.client_id)
    url, user_agent = target.url, web.user_agent if web else None
    await db.commit()  # nada de transacción abierta mientras se espera a la web (sólo se ha leído)
    result = await probe(url, user_agent=user_agent, retry=False)
    return {
        "target_id": target_id,
        "outcome": result.outcome,
        "cause": result.cause,
        "cause_label": cause_label(result.cause),
        "status_code": result.status_code,
        "response_ms": result.response_ms,
        "checked_at": iso(datetime.now(UTC)),
    }


@router.get("/api/web/uptime-targets/{target_id}/history")
async def target_history(
    target_id: int,
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Comprobaciones por día y caídas del periodo (los sondeos se guardan 30 días)."""
    target = await _target_or_404(db, target_id)
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    outages = list(await db.scalars(select(WebOutage).where(
        WebOutage.target_id == target_id,
        (WebOutage.ended_at.is_(None)) | (WebOutage.ended_at >= since),
    ).order_by(WebOutage.started_at.desc())))
    return {
        "target": await _view(db, target),
        "days": await daily_history(db, target_id, days),
        "outages": [outage_view(o, now) for o in outages],
    }


# ── Slack del cliente (sólo admin) ───────────────────────────────────


def _slack_view(web: ClientWebSettings | None) -> SlackSettingsResponse:
    if web is None:
        return SlackSettingsResponse(configured=False, enabled=False, active=False, revoked_at=None,
                                     channel_hint=None, downtime_to_slack=True, user_agent=None, updated_at=None)
    configured = bool(web.slack_webhook_url)
    return SlackSettingsResponse(
        configured=configured,
        enabled=web.slack_enabled,
        active=configured and web.slack_enabled and web.slack_revoked_at is None,
        revoked_at=iso(web.slack_revoked_at),
        channel_hint=web.slack_channel_hint,
        downtime_to_slack=web.downtime_to_slack,
        user_agent=web.user_agent,
        updated_at=iso(web.updated_at),
    )


_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/clients/{client_id}/web/settings/slack", response_model=SlackSettingsResponse)
async def get_slack_settings(
    client_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    await get_client_or_404(client_id, db)
    response.headers.update(_NO_STORE)
    return _slack_view(await db.get(ClientWebSettings, client_id))


@router.put("/api/clients/{client_id}/web/settings/slack", response_model=SlackSettingsResponse)
async def put_slack_settings(
    client_id: int,
    body: SlackSettingsUpdate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    await get_client_or_404(client_id, db)
    now = datetime.now(UTC)
    web = await db.get(ClientWebSettings, client_id)
    if web is None:
        web = ClientWebSettings(client_id=client_id, slack_enabled=False, downtime_to_slack=True)
        db.add(web)
    if body.webhook_url is not None:
        web.slack_webhook_url = encrypt_vault_secret(body.webhook_url.get_secret_value())
        web.slack_revoked_at = None
    if body.enabled and not web.slack_webhook_url:
        raise HTTPException(status_code=422, detail="Pega primero el webhook de Slack del cliente")
    web.slack_enabled = body.enabled
    web.slack_channel_hint = slack_service.normalize_channel(body.channel_hint)
    web.downtime_to_slack = body.downtime_to_slack
    web.user_agent = body.user_agent
    web.updated_by, web.updated_at = admin.id, now
    await db.commit()
    response.headers.update(_NO_STORE)
    return _slack_view(web)


@router.delete("/api/clients/{client_id}/web/settings/slack", response_model=SlackSettingsResponse)
async def delete_slack_settings(
    client_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Quita el webhook (y apaga los avisos). El User-Agent se conserva."""
    await get_client_or_404(client_id, db)
    web = await db.get(ClientWebSettings, client_id)
    if web is not None:
        web.slack_webhook_url = None
        web.slack_enabled = False
        web.slack_revoked_at = None
        web.updated_by, web.updated_at = admin.id, datetime.now(UTC)
        await db.commit()
    response.headers.update(_NO_STORE)
    return _slack_view(web)


@router.post("/api/clients/{client_id}/web/settings/slack/test")
async def test_slack_settings(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Manda un mensaje de prueba al canal del cliente. Si Slack dice que el
    webhook ya no existe, se marca como revocado igual que en el job."""
    client = await get_client_or_404(client_id, db)
    web = await db.get(ClientWebSettings, client_id)
    if web is None or not web.slack_webhook_url:
        raise HTTPException(status_code=422, detail="Este cliente no tiene webhook de Slack")
    try:
        webhook = decrypt_vault_secret(web.slack_webhook_url)
    except ValueError:
        raise HTTPException(status_code=409, detail="No se pudo leer el webhook guardado. Pégalo de nuevo.")
    client_name = client.name
    await db.commit()  # sólo se ha leído: no tener la transacción abierta durante la llamada
    result = await slack_service.send_test_message(webhook, client_name)
    if result.revoked:
        await db.execute(update(ClientWebSettings).where(ClientWebSettings.client_id == client_id).values(
            slack_enabled=False, slack_revoked_at=datetime.now(UTC),
        ))
        await db.commit()
    return {"ok": result.ok, "revoked": result.revoked, "error": None if result.ok else result.error}
