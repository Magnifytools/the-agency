"""Opt-in scheduled messages: local preparation is atomic; only the ledger sends HTTP."""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import noload, selectinload

from backend.config import settings
from backend.db.models import (CommunicationSchedule as Schedule, CommunicationOccurrence as Occurrence,
    CommunicationRequest, Delivery, Notification, Event, EventType, User, UserRole)
from backend.services import deliveries
from backend.services.temporal import business_zone, utc_now_naive, utc_isoformat

KINDS = ("morning", "evening", "meeting", "weekly")
CHANNELS = {"morning": {"in_app", "team_webhook"}, "evening": {"in_app", "team_webhook"},
            "meeting": {"in_app", "extension"}, "weekly": {"owner_dm"}}
TITLES = {"morning": "Plan de la mañana", "evening": "Resumen del día", "meeting": "Reunión próxima", "weekly": "Informe semanal"}
SCHEDULER_STARTED_AT = utc_now_naive()
CALENDAR_FRESHNESS = timedelta(minutes=20)
EXTENSION_MIN_VERSION = "2.2.0"
EXTENSION_DOWNLOAD_URL = "/extension/agency-manager.crx"


def policy_key(kind, user_id):
    return "team:weekly" if kind == "weekly" else f"user:{user_id}:{kind}"


def require_actor(actor, kind):
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Usuario desactivado")
    if kind not in KINDS:
        raise HTTPException(404, "Tipo de aviso desconocido")
    if kind == "weekly" and actor.role != UserRole.admin:
        raise HTTPException(403, "El informe del equipo requiere administrador")
    if kind in ("morning", "evening") and actor.role != UserRole.admin:
        if not any(p.module == "tasks" and p.can_read for p in actor.permissions):
            raise HTTPException(403, "Sin permiso para leer tareas")


def local_instant(day: date, clock: str) -> datetime:
    """Civil slot -> naive UTC; gap rolls forward, fold uses first occurrence."""
    wall = datetime.combine(day, time.fromisoformat(clock))
    for _ in range(181):
        aware = wall.replace(tzinfo=business_zone(), fold=0)
        instant = aware.astimezone(timezone.utc)
        if instant.astimezone(business_zone()).replace(tzinfo=None) == wall:
            return instant.replace(tzinfo=None)
        wall += timedelta(minutes=1)
    raise ValueError("No valid business instant near schedule")


def quiet_until(policy, instant):
    if not policy.quiet_start or not policy.quiet_end:
        return instant
    local = instant.replace(tzinfo=timezone.utc).astimezone(business_zone())
    clock = local.strftime("%H:%M")
    start, end = policy.quiet_start, policy.quiet_end
    if start < end:
        return local_instant(local.date(), end) if start <= clock < end else instant
    if clock >= start:
        return local_instant(local.date() + timedelta(days=1), end)
    if clock < end:
        return local_instant(local.date(), end)
    return instant


async def load_actor(db, ident):
    return await db.scalar(select(User).where(User.id == ident).options(selectinload(User.permissions), noload(User.tasks)).execution_options(populate_existing=True))


async def policy_problem(db, policy, actor, *, channel=None):
    try:
        require_actor(actor, policy.kind)
        if policy.approved_by != actor.id or policy.recipient_id != actor.id:
            raise HTTPException(403, "El responsable de esta política ha cambiado")
        if not policy.enabled:
            return "Aviso desactivado"
        for channel in ([channel] if channel else policy.channels):
            if channel in ("team_webhook", "owner_dm"):
                await deliveries.destination_config(db, "communication", SimpleNamespace(destination_kind=channel, destination_id=policy.destination_id))
        return None
    except HTTPException as exc:
        return str(exc.detail)


async def policy_view(db, policy, actor, kind):
    if policy is None:
        old = (actor.preferences or {}).get("meeting_alerts", {})
        return dict(kind=kind, revision=0, enabled=False, channels=[], destination_id=settings.DISCORD_OWNER_USER_ID or None if kind == "weekly" else None,
                    time=(actor.morning_reminder_time or "08:00") if kind == "morning" else (actor.evening_reminder_time or "18:00") if kind == "evening" else "08:00" if kind == "weekly" else None,
                    minutes_before=old.get("minutes_before", 30) if kind == "meeting" else None,
                    quiet_start=None, quiet_end=None, state="needs_review", reason="Elige los canales y guarda tu consentimiento; los valores antiguos no activan avisos", effective_from=None)
    owner = await load_actor(db, policy.approved_by)
    problem = await policy_problem(db, policy, owner)
    return dict(kind=kind, revision=policy.revision, enabled=policy.enabled, channels=policy.channels, destination_id=policy.destination_id,
                time=policy.time, minutes_before=policy.minutes_before, quiet_start=policy.quiet_start,
                quiet_end=policy.quiet_end, state="disabled" if not policy.enabled else "blocked" if problem else "ready",
                reason=problem, effective_from=utc_isoformat(policy.effective_from), approved_by=policy.approved_by)


async def catalog(db, actor):
    policies = []
    for kind in KINDS:
        if kind == "weekly" and actor.role != UserRole.admin:
            continue
        policy = await db.scalar(select(Schedule).where(Schedule.policy_key == policy_key(kind, actor.id)))
        policies.append(await policy_view(db, policy, actor, kind))
    return dict(user_id=actor.id, timezone=settings.AGENCY_TIMEZONE, scheduler_enabled=settings.SCHEDULED_COMMUNICATIONS_ENABLED,
                extension_min_version=EXTENSION_MIN_VERSION, extension_download_url=EXTENSION_DOWNLOAD_URL, policies=policies)


async def save_policy(db, actor, kind, body):
    # Serializes first creation too, including concurrent admins adopting singleton.
    if kind not in KINDS or (kind == "weekly" and actor.role != UserRole.admin):
        raise HTTPException(403, "No puedes configurar este aviso")
    await db.execute(select(User.id).where(User.id == actor.id).with_for_update())
    if kind == "weekly":
        from sqlalchemy import text
        await db.execute(text("SELECT pg_advisory_xact_lock(76241310)"))
    key = policy_key(kind, actor.id)
    policy = await db.scalar(select(Schedule).where(Schedule.policy_key == key).with_for_update().execution_options(populate_existing=True))
    if body.revision != (policy.revision if policy else 0):
        raise HTTPException(409, "La configuración cambió. Recarga antes de guardar; tu borrador se conserva")
    if kind != "weekly" and body.destination_id is not None:
        raise HTTPException(422, "Solo el informe semanal admite destinatario técnico")
    channels = sorted(set(body.channels))
    if not set(channels) <= CHANNELS[kind] or (body.enabled and not channels):
        raise HTTPException(422, "Selecciona al menos un canal disponible")
    if kind == "meeting" and (body.time is not None or body.minutes_before is None):
        raise HTTPException(422, "Las reuniones requieren antelación, no hora fija")
    if kind != "meeting" and (body.time is None or body.minutes_before is not None):
        raise HTTPException(422, "Este aviso requiere hora fija")
    if kind == "weekly" and body.time != "08:00":
        raise HTTPException(422, "El informe semanal se prepara el sábado a las 08:00")
    if bool(body.quiet_start) != bool(body.quiet_end) or (body.quiet_start and body.quiet_start == body.quiet_end):
        raise HTTPException(422, "Indica inicio y fin distintos para el silencio")
    now = utc_now_naive()
    if policy is None:
        policy = Schedule(policy_key=key, kind=kind, approved_by=actor.id, recipient_id=actor.id,
                          effective_from=now, revision=0)
        db.add(policy)
    # Enabling again starts now; existing occurrence keys still prevent replay.
    if body.enabled and (not policy.enabled or policy.approved_by != actor.id):
        policy.effective_from = now
    policy.approved_by = policy.recipient_id = actor.id
    policy.destination_id = body.destination_id
    policy.enabled, policy.channels = body.enabled, channels
    policy.time, policy.minutes_before = body.time, body.minutes_before
    policy.quiet_start, policy.quiet_end = body.quiet_start, body.quiet_end
    policy.revision += 1
    await db.flush()
    # Pending transports are revalidated per part by the worker. No data is sent here.
    await db.commit()
    return await policy_view(db, policy, actor, kind)


async def occurrence_problem(db, occurrence, policy, actor):
    problem = await policy_problem(db, policy, actor, channel=occurrence.channel)
    if problem:
        return problem
    if occurrence.due_at < policy.effective_from:
        return "Esta ocurrencia es anterior a la nueva activación"
    if occurrence.recipient_id != policy.recipient_id or occurrence.channel not in policy.channels:
        return "Destinatario o canal desactivado"
    if occurrence.kind == "meeting":
        event = await db.get(Event, occurrence.event_id, populate_existing=True) if occurrence.event_id else None
        if not event or event.user_id != actor.id or event.event_type != EventType.meeting or event.start_time != occurrence.event_start:
            return "La reunión se canceló o cambió de fecha"
        if event.source == "google":
            if not actor.google_calendar_connected or event.source_calendar_id != (actor.google_calendar_id or "primary"):
                return "Evento legado o de otro calendario: sincroniza el calendario actual para verificarlo"
            synced = actor.google_calendar_synced_at
            now = utc_now_naive()
            if not synced or synced < SCHEDULER_STARTED_AT or not timedelta(0) <= now - synced <= CALENDAR_FRESHNESS:
                return "Reunión pendiente de sincronización completa reciente; sincroniza Google Calendar en Ajustes"
    return None


async def authorize_scheduled(db, source, actor, *, write=True):
    occurrence = await db.scalar(select(Occurrence).where(Occurrence.request_id == source.id).execution_options(populate_existing=True))
    if (not occurrence or source.kind != f"scheduled_{occurrence.kind}" or source.destination_kind != occurrence.channel
        or source.scope != ("team" if occurrence.kind == "weekly" else "mine")
        or source.period_start != occurrence.period_start or source.period_end != occurrence.period_end
        or source.owner_id != occurrence.recipient_id):
        raise HTTPException(404, "Ocurrencia no encontrada")
    if actor.id != source.owner_id and actor.role != UserRole.admin:
        raise HTTPException(403, "Este aviso pertenece a otra persona")
    require_actor(actor, occurrence.kind)
    if not write:
        return occurrence
    policy = await db.get(Schedule, occurrence.schedule_id, populate_existing=True)
    if actor.id != policy.approved_by or source.owner_id != policy.approved_by:
        raise HTTPException(403, "El responsable del aviso cambió")
    problem = await occurrence_problem(db, occurrence, policy, actor)
    if problem:
        raise HTTPException(409, problem)
    if utc_now_naive() >= occurrence.expires_at:
        raise HTTPException(409, "La ventana del aviso ha terminado")
    return occurrence


async def effective_due(db, occurrence, policy):
    if occurrence.kind == "meeting":
        return occurrence.expires_at - timedelta(minutes=policy.minutes_before)
    return local_instant(occurrence.period_end + timedelta(days=1) if occurrence.kind == "weekly" else occurrence.period_start, policy.time)


async def defer_delivery(db, row, source, attempt=None):
    """Pause automation during silence/rollout; confirmed prefixes remain intact."""
    if row.source_kind != "communication" or not source.kind.startswith("scheduled_"):
        return False
    occurrence = await db.scalar(select(Occurrence).where(Occurrence.request_id == source.id))
    policy = await db.get(Schedule, occurrence.schedule_id, populate_existing=True)
    now = utc_now_naive()
    available = quiet_until(policy, max(now, await effective_due(db, occurrence, policy)))
    if not settings.SCHEDULED_COMMUNICATIONS_ENABLED:
        available = max(available, now + timedelta(minutes=1))
    if available <= now:
        return False
    row.available_at = available
    row.status = "expired" if available >= occurrence.expires_at else "pending"
    row.message = "Ventana terminada durante el silencio" if row.status == "expired" else "En espera por horario de silencio o planificador pausado"
    if attempt:
        attempt.status = "deferred"
    await db.commit()
    return True


async def _add_occurrence(db, policy, channel, start, end, due, expires, *, event=None):
    if event and expires > policy.effective_from:
        due = max(due, policy.effective_from)  # opt-in can still alert an upcoming meeting
    if due < policy.effective_from:
        return  # no inferred consent or historical backfill
    identity = [policy.policy_key, channel, start, end, event.id if event else None, event.start_time if event else None]
    values = dict(occurrence_key=deliveries.fingerprint(identity), schedule_id=policy.id,
                  recipient_id=policy.recipient_id, kind=policy.kind, channel=channel,
                  period_start=start, period_end=end, due_at=due, expires_at=expires,
                  event_id=event.id if event else None, event_start=event.start_time if event else None,
                  state="cancelled" if event and event.alert_sent_at else "planned",
                  reason="Aviso legado sin recibo; no se repetirá automáticamente" if event and event.alert_sent_at else None)
    await db.execute(insert(Occurrence).values(**values).on_conflict_do_update(
        index_elements=["occurrence_key"], set_={"due_at": due, "expires_at": expires},
        where=or_(Occurrence.state.in_(["planned", "blocked"]),
                  (Occurrence.state == "ready") & (Occurrence.channel == "extension"))))


async def plan_policy(db, policy, now):
    local = now.replace(tzinfo=timezone.utc).astimezone(business_zone())
    today = local.date()
    actor = await load_actor(db, policy.approved_by)
    if policy.kind in ("morning", "evening"):
        from backend.services.daily_reminders import is_working_day
        for day in (today - timedelta(days=1), today):
            if not await is_working_day(db, day, actor.region if actor else None):
                continue
            due = local_instant(day, policy.time)
            expires = local_instant(day + timedelta(days=1), "00:00")
            if policy.kind == "morning":
                evening = await db.scalar(select(Schedule).where(Schedule.policy_key == policy_key("evening", policy.recipient_id)))
                end_clock = evening.time if evening and evening.enabled else "18:00"
                recap_at = local_instant(day, end_clock)
                expires = recap_at if recap_at > due else expires
            for channel in policy.channels:
                await _add_occurrence(db, policy, channel, day, day, due, expires)
    elif policy.kind == "weekly":
        saturday = today - timedelta(days=(today.weekday() - 5) % 7)
        monday = saturday - timedelta(days=5)
        for channel in policy.channels:
            await _add_occurrence(db, policy, channel, monday, saturday - timedelta(days=1),
                                  local_instant(saturday, "08:00"), local_instant(saturday + timedelta(days=2), "08:00"))
    else:
        after = 0
        while True:
            events = (await db.execute(select(Event).where(Event.user_id == policy.recipient_id, Event.id > after,
                Event.event_type == EventType.meeting, Event.is_all_day.is_(False), Event.start_time >= datetime.combine(today - timedelta(days=1), time.min),
                Event.start_time < datetime.combine(today + timedelta(days=2), time.min)).order_by(Event.id).limit(100))).scalars().all()
            if not events:
                break
            for event in events:
                starts = local_instant(event.start_time.date(), event.start_time.time().isoformat())
                due = starts - timedelta(minutes=policy.minutes_before)
                for channel in policy.channels:
                    await _add_occurrence(db, policy, channel, event.start_time.date(), event.start_time.date(), due, starts, event=event)
            after = events[-1].id


async def render_occurrence(db, occurrence, actor):
    if occurrence.kind == "morning":
        from backend.services.daily_reminders import generate_morning_plan
        return await generate_morning_plan(db, actor, day=occurrence.period_start)
    if occurrence.kind == "evening":
        from backend.services.daily_reminders import generate_evening_recap
        return await generate_evening_recap(db, actor, occurrence.period_start)
    if occurrence.kind == "weekly":
        from backend.services.weekly_report_service import generate_weekly_report
        return await generate_weekly_report(db, period_start=occurrence.period_start, period_end=occurrence.period_end)
    event = await db.get(Event, occurrence.event_id)
    return f"Reunión a las {event.start_time:%H:%M}: {event.title}"


async def prepare_occurrence(db, occurrence, now):
    # Preparation may run after a long scan; never use its stale start time.
    now = utc_now_naive()
    policy = await db.scalar(select(Schedule).where(Schedule.id == occurrence.schedule_id).with_for_update().execution_options(populate_existing=True))
    actor = await load_actor(db, policy.approved_by)
    if now >= occurrence.expires_at:
        occurrence.state, occurrence.reason = "expired", "La ventana del aviso terminó"
        return
    problem = await occurrence_problem(db, occurrence, policy, actor)
    if problem:
        occurrence.state, occurrence.reason = "blocked", problem
        return
    available = quiet_until(policy, max(now, occurrence.due_at))
    if available >= occurrence.expires_at:
        occurrence.state, occurrence.reason = "expired", "El silencio termina después de la ventana del aviso"
        return
    if available > now:
        occurrence.state, occurrence.reason = "planned", "En espera de su horario o del fin del silencio"
        return
    content = await render_occurrence(db, occurrence, actor)
    if occurrence.channel == "in_app":
        note = Notification(user_id=actor.id, type=f"scheduled_{occurrence.kind}", title=TITLES[occurrence.kind], message=content,
                            link_url="/settings#notifications", dedupe_key=f"scheduled:{occurrence.occurrence_key}")
        db.add(note)
        await db.flush()
        occurrence.notification_id, occurrence.state = note.id, "local_delivered"
        occurrence.reason = "Disponible en la app; no implica que se haya leído"
        return
    source = CommunicationRequest(request_key=occurrence.occurrence_key, owner_id=actor.id, kind=f"scheduled_{occurrence.kind}",
        scope="team" if occurrence.kind == "weekly" else "mine", period_start=occurrence.period_start,
        period_end=occurrence.period_end, title=TITLES[occurrence.kind], content=content, destination_kind=occurrence.channel)
    db.add(source)
    await db.flush()
    occurrence.request_id = source.id
    await db.flush()
    if occurrence.channel != "extension":
        delivery = await deliveries.stage_delivery(db, "communication", source.id, actor)
        delivery.expires_at = occurrence.expires_at
    occurrence.state, occurrence.reason = "ready", "Disponible para la extensión; entrega de escritorio no confirmada" if occurrence.channel == "extension" else "Preparado; consulta el recibo de envío"


async def run_scheduler_once(session_factory, *, now=None):
    if not settings.SCHEDULED_COMMUNICATIONS_ENABLED:
        return 0
    now = now or utc_now_naive()
    # Page by primary key, never silently truncate the eligible population.
    after = 0
    while True:
        async with session_factory() as db:
            policies = (await db.execute(select(Schedule).where(Schedule.enabled.is_(True), Schedule.id > after)
                        .order_by(Schedule.id).limit(50))).scalars().all()
            if not policies:
                break
            for policy in policies:
                await plan_policy(db, policy, now)
            after = policies[-1].id
            await db.commit()
    prepared = 0
    # One locked occurrence per transaction; a crash cannot leave half a request.
    async with session_factory() as db:
        ids = (await db.scalars(select(Occurrence.id).where(Occurrence.state.in_(["planned", "blocked"]), Occurrence.due_at <= now)
                               .order_by(Occurrence.updated_at, Occurrence.id).limit(500))).all()
    for ident in ids:
        async with session_factory() as db:
            occurrence = await db.scalar(select(Occurrence).where(Occurrence.id == ident, Occurrence.state.in_(["planned", "blocked"]))
                                          .with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if not occurrence:
                continue
            try:
                async with db.begin_nested():
                    await prepare_occurrence(db, occurrence, now)
            except Exception as exc:
                # Roll back local preparation only; expose failure without raw credentials.
                occurrence = await db.get(Occurrence, ident, populate_existing=True)
                occurrence.state = "blocked"
                occurrence.reason = "No se pudo preparar el aviso; se volverá a comprobar dentro de su ventana (" + type(exc).__name__ + ")"
            # Rotate blocked/quiet rows behind unchecked ones; one bad prefix
            # of 500 occurrences must not starve later eligible work.
            occurrence.updated_at = func.now()
            await db.commit()
            prepared += 1
    return prepared


async def scheduler_loop():
    import asyncio
    import logging
    from backend.db.database import async_session
    while True:
        try:
            await run_scheduler_once(async_session)
        except Exception as exc:
            logging.error("Scheduled preparation failed (%s); no provider call during preparation", type(exc).__name__)
        await asyncio.sleep(60)
