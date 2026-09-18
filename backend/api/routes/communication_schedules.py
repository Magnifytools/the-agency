"""Own opt-in schedules and durable occurrence history. No inline provider calls."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_admin
from backend.db.database import get_db
from backend.db.models import CommunicationSchedule as Schedule, CommunicationOccurrence as Occurrence, CommunicationRequest, Delivery, DiscordSettings, User, UserRole
from backend.services import scheduled_communications as service, deliveries
from backend.services.temporal import utc_now_naive, utc_isoformat

router = APIRouter(prefix="/api/communication-schedules", tags=["communication-schedules"])
CLOCK = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class PolicyUpdate(BaseModel):
    revision: int = Field(ge=0)
    enabled: bool
    destination_id: str | None = Field(default=None, pattern=r"^\d{5,30}$")
    channels: list[str] = Field(max_length=2)
    time: str | None = Field(default=None, pattern=CLOCK)
    minutes_before: int | None = Field(default=None, ge=5, le=120)
    quiet_start: str | None = Field(default=None, pattern=CLOCK)
    quiet_end: str | None = Field(default=None, pattern=CLOCK)

    model_config = {"extra": "forbid"}


class DiscordConfiguration(BaseModel):
    webhook_url: str | None = Field(default=None, min_length=1, max_length=500)
    bot_token: str | None = Field(default=None, min_length=1, max_length=500)
    model_config = {"extra": "forbid"}


@router.get("/discord-configuration")
async def discord_configuration(db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin)):
    config = await db.scalar(select(DiscordSettings).limit(1))
    return {"webhook_configured": bool(config and config.webhook_url or service.settings.DISCORD_WEBHOOK_URL),
            "bot_token_configured": bool(config and config.bot_token)}


@router.put("/discord-configuration")
async def update_discord_configuration(body: DiscordConfiguration, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin)):
    from sqlalchemy import text
    from backend.core.security import encrypt_vault_secret
    if body.webhook_url is not None and not deliveries.WEBHOOK_RE.fullmatch(body.webhook_url.strip()):
        raise HTTPException(422, "Introduce un webhook válido de Discord")
    if body.bot_token is not None and not body.bot_token.strip():
        raise HTTPException(422, "El token no puede estar vacío")
    await db.execute(text("SELECT pg_advisory_xact_lock(76241311)"))
    config = await db.scalar(select(DiscordSettings).limit(1).with_for_update())
    if config is None:
        config = DiscordSettings()
        db.add(config)
    if body.webhook_url is not None:
        config.webhook_url = encrypt_vault_secret(body.webhook_url.strip())
    if body.bot_token is not None:
        config.bot_token = encrypt_vault_secret(body.bot_token.strip())
    await db.commit()
    return await discord_configuration(db, actor)


@router.get("")
async def get_catalog(db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    return await service.catalog(db, actor)


@router.get("/history")
async def get_history(limit: int = Query(30, ge=1, le=100), before: int | None = None,
                      db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    own = Occurrence.recipient_id == actor.id
    if actor.role == UserRole.admin:
        own = or_(own, Occurrence.kind == "weekly")
    query = select(Occurrence).where(own)
    if actor.role != UserRole.admin:
        query = query.where(Occurrence.kind != "weekly")
    if before is not None:
        query = query.where(Occurrence.id < before)
    rows = (await db.scalars(query.order_by(Occurrence.id.desc()).limit(limit))).all()
    result = []
    for occurrence in rows:
        receipt = None
        if occurrence.request_id:
            row = await db.scalar(select(Delivery).where(Delivery.source_kind == "communication", Delivery.source_id == occurrence.request_id)
                                  .order_by(Delivery.created_at.desc()).limit(1))
            if row:
                source = await db.get(CommunicationRequest, occurrence.request_id)
                try:
                    await service.authorize_scheduled(db, source, actor, write=False)
                    can_write = False
                    try:
                        await service.authorize_scheduled(db, source, actor)
                        can_write = True
                    except HTTPException:
                        pass
                    receipt = await deliveries.receipt(db, row, source, writable=can_write)
                except HTTPException:
                    pass
        state, reason = occurrence.state, occurrence.reason
        if state in ("ready", "planned", "blocked") and not receipt:
            policy = await db.get(Schedule, occurrence.schedule_id)
            owner = await service.load_actor(db, policy.approved_by)
            problem = await service.occurrence_problem(db, occurrence, policy, owner)
            if utc_now_naive() >= occurrence.expires_at:
                state, reason = "expired", "La ventana del aviso terminó"
            elif problem:
                state, reason = "blocked", problem
        result.append(dict(id=occurrence.id, kind=occurrence.kind, channel=occurrence.channel, state=state, reason=reason,
                           period_start=occurrence.period_start, period_end=occurrence.period_end,
                           due_at=utc_isoformat(occurrence.due_at), expires_at=utc_isoformat(occurrence.expires_at), receipt=receipt))
    return result


@router.get("/extension-upcoming")
async def extension_upcoming(db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    policy = await db.scalar(select(Schedule).where(Schedule.policy_key == service.policy_key("meeting", actor.id)))
    view = await service.policy_view(db, policy, actor, "meeting")
    response = dict(user_id=actor.id, timezone=service.settings.AGENCY_TIMEZONE, scheduler_enabled=service.settings.SCHEDULED_COMMUNICATIONS_ENABLED,
        extension_min_version=service.EXTENSION_MIN_VERSION, extension_download_url=service.EXTENSION_DOWNLOAD_URL,
        policy=view, occurrences=[])
    now = utc_now_naive()
    if not service.settings.SCHEDULED_COMMUNICATIONS_ENABLED or view["state"] != "ready" or "extension" not in policy.channels or service.quiet_until(policy, now) > now:
        return response
    # Eligibility is server-authorized; a read never confirms desktop presentation.
    rows = (await db.scalars(select(Occurrence).where(Occurrence.recipient_id == actor.id,
            Occurrence.channel == "extension", Occurrence.state == "ready", Occurrence.due_at <= now,
            Occurrence.expires_at > now).order_by(Occurrence.expires_at, Occurrence.id))).all()
    for occurrence in rows:
        if await service.occurrence_problem(db, occurrence, policy, actor) or await service.effective_due(db, occurrence, policy) > now:
            continue
        source = await db.get(CommunicationRequest, occurrence.request_id)
        response["occurrences"].append(dict(occurrence_id=occurrence.id, title=source.title, content=source.content,
            start_time=utc_isoformat(service.local_instant(occurrence.event_start.date(), occurrence.event_start.time().isoformat())), expires_at=utc_isoformat(occurrence.expires_at),
            minutes_until=max(0, int((occurrence.expires_at - now).total_seconds() / 60))))
    return response


@router.put("/{kind}")
async def update_policy(kind: str, body: PolicyUpdate, db: AsyncSession = Depends(get_db), actor: User = Depends(get_current_user)):
    return await service.save_policy(db, actor, kind, body)
