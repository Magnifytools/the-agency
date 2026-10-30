"""Bloques de trabajo ↔ Google Calendar, en los dos sentidos (fase 4).

Quien lo activa (Ajustes → Google Calendar) da el permiso ``calendar.app.created``
y la app crea en su cuenta un calendario aparte, "The Agency"
(``user_blocks_calendars``). Sólo se escribe ahí: nunca en sus otros
calendarios. Si algo va mal, se borra ese calendario y nada más.

Cada minuto (job ``calendar_blocks``) se concilian sus bloques con los eventos
de ese calendario entre el lunes de esta semana y 35 días después:

- Bloque sin evento → se crea el evento (lleva ``agency_block_id`` en sus
  propiedades privadas: sólo se tocan eventos marcados así).
- Cambio en la app → se actualiza el evento. Cambio en Google (mover o estirar)
  → se actualiza el bloque. Los dos a la vez → gana el último. Un cambio en
  Google que un bloque no admite (otro día, más de 12 h, todo el día) se
  deshace devolviendo al evento la hora del bloque.
- Evento borrado en Google → se borra el bloque (nunca la tarea). Bloque borrado
  en la app → se borra el evento. Si el bloque vuelve (⌘Z) después de borrarse
  su evento, se crea otro.

La red va fuera de la transacción; después se guarda comprobando que el bloque
no ha cambiado entretanto (si cambió, lo recoge la siguiente pasada).
``updated_at`` y ``google_synced_at`` se escriben con el mismo ``now()`` de
Postgres: "cambió en la app" es ``updated_at > google_synced_at``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import noload

from backend.config import settings
from backend.db.models import Client, Task, TaskTimeBlock, User, UserBlocksCalendar
from backend.services.temporal import business_today, business_zone

logger = logging.getLogger(__name__)

BLOCK_PROPERTY = "agency_block_id"
CALENDAR_NAME = "The Agency"
WINDOW_DAYS = 35
MAX_BLOCK = timedelta(hours=12)


# ── Lo que se compara ────────────────────────────────────────────────────────

@dataclass
class BlockState:
    id: int
    starts_at: datetime
    ends_at: datetime
    updated_at: datetime
    google_event_id: str | None
    google_event_updated: str | None
    google_synced_at: datetime | None
    summary: str
    description: str

    @property
    def changed_here(self) -> bool:
        return self.google_synced_at is None or self.updated_at > self.google_synced_at


@dataclass
class EventState:
    id: str
    block_id: int | None
    cancelled: bool
    updated: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    summary: str = ""
    description: str = ""


@dataclass
class Plan:
    create: list[BlockState] = field(default_factory=list)
    patch: list[tuple[BlockState, str]] = field(default_factory=list)
    from_google: list[tuple[BlockState, EventState]] = field(default_factory=list)
    delete_blocks: list[BlockState] = field(default_factory=list)
    delete_events: list[str] = field(default_factory=list)


def _instant(value: str) -> datetime:
    """RFC 3339 de Google → UTC sin zona."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def _fits_a_block(event: EventState) -> bool:
    if event.starts_at is None or event.ends_at is None or event.ends_at <= event.starts_at:
        return False
    if event.ends_at - event.starts_at > MAX_BLOCK:
        return False
    return (event.ends_at - timedelta(microseconds=1)).date() == event.starts_at.date()


def plan_sync(blocks: list[BlockState], events: list[EventState]) -> Plan:
    """Qué hay que hacer para que bloques y eventos marcados digan lo mismo."""
    plan = Plan()
    by_block = {event.block_id: event for event in events if event.block_id is not None and not event.cancelled}
    by_id = {event.id: event for event in events}
    block_ids = {block.id for block in blocks}
    for block in blocks:
        event = by_id.get(block.google_event_id) if block.google_event_id else None
        if event is None or event.cancelled:
            # Un evento creado cuya respuesta no llegó a guardarse se reconoce por su marca.
            event = by_block.get(block.id, event)
        if event is None or event.cancelled:
            if block.google_event_id is None or block.changed_here:
                # Sin evento, o el bloque volvió (⌘Z) después de borrarse el suyo.
                plan.create.append(block)
            else:
                plan.delete_blocks.append(block)
            continue
        # Sin ``updated`` guardado nunca se concilió: manda la app.
        changed_there = block.google_event_updated is not None and event.updated != block.google_event_updated
        if changed_there and block.changed_here and _instant(event.updated) < block.updated_at:
            changed_there = False  # los dos cambiaron: gana el último, el de la app
        if changed_there:
            if _fits_a_block(event):
                plan.from_google.append((block, event))
            else:
                plan.patch.append((block, event.id))
            continue
        if block.changed_here or (event.summary, event.description) != (block.summary, block.description) \
                or (event.starts_at, event.ends_at) != (block.starts_at, block.ends_at):
            plan.patch.append((block, event.id))
    for event in events:
        if not event.cancelled and event.block_id is not None and event.block_id not in block_ids:
            plan.delete_events.append(event.id)
    return plan


# ── Google (síncrono: se llama en un hilo) ───────────────────────────────────

def _service(encrypted_refresh_token: str):
    from googleapiclient.discovery import build

    from backend.services.google_calendar_service import BLOCKS_SCOPE, SCOPES, _get_credentials

    credentials = _get_credentials(encrypted_refresh_token, scopes=[*SCOPES, BLOCKS_SCOPE])
    if credentials is None:
        raise ValueError("Calendar credentials unavailable")
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def create_blocks_calendar(encrypted_refresh_token: str) -> str:
    calendar = _service(encrypted_refresh_token).calendars().insert(body={
        "summary": CALENDAR_NAME,
        "description": "Bloques de trabajo de The Agency. Se pueden mover aquí o en la app.",
        "timeZone": settings.AGENCY_TIMEZONE,
    }).execute()
    return calendar["id"]


def delete_blocks_calendar(encrypted_refresh_token: str, calendar_id: str) -> None:
    _service(encrypted_refresh_token).calendars().delete(calendarId=calendar_id).execute()


def _civil(value: dict) -> datetime | None:
    instant = value.get("dateTime")
    if not instant:
        return None  # todo el día: no es un bloque
    parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    return parsed.astimezone(business_zone()).replace(tzinfo=None) if parsed.tzinfo else parsed


def _event_state(item: dict) -> EventState:
    raw = ((item.get("extendedProperties") or {}).get("private") or {}).get(BLOCK_PROPERTY)
    return EventState(
        id=item["id"],
        block_id=int(raw) if raw and str(raw).isdigit() else None,
        cancelled=item.get("status") == "cancelled",
        updated=item.get("updated", ""),
        starts_at=_civil(item.get("start") or {}),
        ends_at=_civil(item.get("end") or {}),
        summary=item.get("summary", ""),
        description=item.get("description", ""),
    )


def list_block_events(encrypted_refresh_token: str, calendar_id: str, start: datetime, end: datetime) -> list[EventState]:
    service = _service(encrypted_refresh_token)
    zone = business_zone()
    events, token = [], None
    while True:
        result = service.events().list(
            calendarId=calendar_id, timeMin=start.replace(tzinfo=zone).isoformat(),
            timeMax=end.replace(tzinfo=zone).isoformat(), singleEvents=True, showDeleted=True,
            maxResults=250, **({"pageToken": token} if token else {}),
        ).execute()
        events.extend(_event_state(item) for item in result.get("items", []))
        token = result.get("nextPageToken")
        if not token:
            return events


def get_block_events(encrypted_refresh_token: str, calendar_id: str, event_ids: list[str]) -> list[EventState]:
    """Eventos sueltos que no salen en la ventana (movidos fuera en Google). Borrados del todo: no vienen."""
    service = _service(encrypted_refresh_token)
    events = []
    for event_id in event_ids:
        try:
            events.append(_event_state(service.events().get(calendarId=calendar_id, eventId=event_id).execute()))
        except Exception as error:
            if not _gone(error):
                raise
    return events


def _event_body(block: BlockState) -> dict:
    zone = settings.AGENCY_TIMEZONE
    return {
        "summary": block.summary,
        "description": block.description,
        "start": {"dateTime": block.starts_at.isoformat(), "timeZone": zone},
        "end": {"dateTime": block.ends_at.isoformat(), "timeZone": zone},
        "extendedProperties": {"private": {BLOCK_PROPERTY: str(block.id)}},
    }


def run_plan(encrypted_refresh_token: str, calendar_id: str, plan: Plan) -> dict:
    """Escribe en Google. Devuelve ``{block_id: (event_id, updated)}`` de lo creado o cambiado."""
    service = _service(encrypted_refresh_token)
    written: dict[int, tuple[str, str]] = {}
    for block in plan.create:
        event = service.events().insert(calendarId=calendar_id, body=_event_body(block)).execute()
        written[block.id] = (event["id"], event.get("updated", ""))
    for block, event_id in plan.patch:
        event = service.events().patch(calendarId=calendar_id, eventId=event_id, body=_event_body(block)).execute()
        written[block.id] = (event["id"], event.get("updated", ""))
    for event_id in plan.delete_events:
        try:
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as error:  # ya borrado en Google: nada que hacer
            if not _gone(error):
                raise
    return written


def _gone(error: Exception) -> bool:
    return getattr(getattr(error, "resp", None), "status", None) in (404, 410)


# ── Pasada de una persona ────────────────────────────────────────────────────

async def blocks_calendar_id(db, user_id: int) -> str | None:
    """El calendario "The Agency" donde publica esa persona; None si no publica."""
    return await db.scalar(select(UserBlocksCalendar.calendar_id).where(UserBlocksCalendar.user_id == user_id))


async def forget_blocks(db, user_id: int) -> None:
    """Deja de publicar: olvida el calendario y la relación bloque ↔ evento.

    ``delete()``/``update()`` masivos: fuera del Deshacer, como el resto de la
    conexión con Google. ``updated_at`` se conserva para que no parezca un
    cambio del bloque.
    """
    await db.execute(delete(UserBlocksCalendar).where(UserBlocksCalendar.user_id == user_id))
    await db.execute(
        update(TaskTimeBlock).where(TaskTimeBlock.user_id == user_id)
        .values(google_event_id=None, google_event_updated=None, google_synced_at=None,
                updated_at=TaskTimeBlock.updated_at)
    )


async def _still_publishing(db, user_id: int, calendar_id: str) -> bool:
    """Si sigue publicando en ESE calendario (no lo desactivó a mitad). Bloquea la fila."""
    current = await db.scalar(
        select(UserBlocksCalendar.calendar_id).where(UserBlocksCalendar.user_id == user_id).with_for_update()
    )
    return current == calendar_id


def window(today: date) -> tuple[datetime, datetime]:
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, datetime.min.time())
    return start, start + timedelta(days=WINDOW_DAYS)


def _summary(title: str, client_name: str | None) -> str:
    return f"{title} · {client_name}" if client_name else title


def _description(task_id: int) -> str:
    # La app vive donde vuelve Google tras dar permiso: misma URL pública.
    origin = urlsplit(settings.GOOGLE_REDIRECT_URI)
    return f"Bloque de trabajo de The Agency.\n{origin.scheme}://{origin.netloc}/tasks?task={task_id}"


async def sync_user(session_maker, user_id: int) -> dict:
    """Una pasada para una persona. Devuelve cuánto cambió (para el log)."""
    import anyio

    start, end = window(business_today())
    async with session_maker() as db:
        user = await db.get(User, user_id, options=[noload("*")])
        calendar_id = await blocks_calendar_id(db, user_id)
        if user is None or not user.is_active or not user.google_calendar_connected \
                or not user.google_refresh_token or not calendar_id:
            return {}
        token = user.google_refresh_token
    try:
        events = await anyio.to_thread.run_sync(lambda: list_block_events(token, calendar_id, start, end))
    except Exception as error:
        if not _gone(error):
            raise
        # Borró el calendario "The Agency" en Google: deja de publicar.
        async with session_maker() as db:
            if await _still_publishing(db, user_id, calendar_id):
                await forget_blocks(db, user_id)
                await db.commit()
        return {"calendar_gone": 1}
    # Los bloques de la ventana y los que tienen evento en ella aunque se hayan
    # movido fuera en la app: sin ellos, su evento parecería huérfano y se borraría.
    marked = {event.block_id for event in events if event.block_id is not None}
    async with session_maker() as db:
        rows = (await db.execute(
            select(TaskTimeBlock, Task.title, Client.name)
            .join(Task, Task.id == TaskTimeBlock.task_id)
            .outerjoin(Client, Client.id == Task.client_id)
            .where(TaskTimeBlock.user_id == user_id, or_(
                and_(TaskTimeBlock.starts_at >= start, TaskTimeBlock.starts_at < end),
                TaskTimeBlock.id.in_(marked),
            ))
        )).all()
        blocks = [BlockState(
            id=block.id, starts_at=block.starts_at, ends_at=block.ends_at, updated_at=block.updated_at,
            google_event_id=block.google_event_id, google_event_updated=block.google_event_updated,
            google_synced_at=block.google_synced_at, summary=_summary(title, client_name),
            description=_description(block.task_id),
        ) for block, title, client_name in rows]
    # Y al revés: un evento movido fuera de la ventana en Google no sale en la
    # lista, pero no está borrado. Se pide uno a uno antes de decidir.
    listed = {event.id for event in events}
    missing = [block.google_event_id for block in blocks
               if block.google_event_id and block.google_event_id not in listed]
    if missing:
        events += await anyio.to_thread.run_sync(lambda: get_block_events(token, calendar_id, missing))
    plan = plan_sync(blocks, events)
    written = await anyio.to_thread.run_sync(lambda: run_plan(token, calendar_id, plan))
    seen = {block.id: block for block in blocks}
    applied = {"created": len(plan.create), "patched": len(plan.patch), "from_google": 0,
               "deleted_blocks": 0, "deleted_events": len(plan.delete_events)}
    async with session_maker() as db:
        if not await _still_publishing(db, user_id, calendar_id):
            return applied  # lo desactivó a mitad: no se resucita nada
        for block_id, (event_id, updated) in written.items():
            row = await _unchanged(db, block_id, seen[block_id])
            if row is not None:
                row.google_event_id, row.google_event_updated = event_id, updated
                row.google_synced_at = func.now()
        for block, event in plan.from_google:
            row = await _unchanged(db, block.id, block)
            if row is not None:
                row.starts_at, row.ends_at = event.starts_at, event.ends_at
                row.google_event_id, row.google_event_updated = event.id, event.updated
                row.google_synced_at = func.now()
                applied["from_google"] += 1
        for block in plan.delete_blocks:
            row = await _unchanged(db, block.id, block)
            if row is not None:
                await db.delete(row)
                applied["deleted_blocks"] += 1
        await db.commit()
    return applied


async def _unchanged(db, block_id: int, seen: BlockState) -> TaskTimeBlock | None:
    """El bloque tal como se leyó; si cambió entretanto, None (lo recoge la siguiente pasada)."""
    row = (await db.execute(
        select(TaskTimeBlock).where(TaskTimeBlock.id == block_id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None or row.updated_at != seen.updated_at:
        return None
    return row


async def sync_all(session_maker) -> dict:
    """El job: una pasada por cada persona que publica sus bloques."""
    from backend.services.google_calendar_service import authorization_needs_reconnect

    async with session_maker() as db:
        user_ids = (await db.execute(
            select(User.id).join(UserBlocksCalendar, UserBlocksCalendar.user_id == User.id)
            .where(User.is_active.is_(True), User.google_calendar_connected.is_(True))
        )).scalars().all()
    failed = 0
    for user_id in user_ids:
        try:
            result = await sync_user(session_maker, user_id)
            if any(result.values()):
                logger.info("Calendar blocks synced for user_id=%s: %s", user_id, result)
        except Exception as error:
            failed += 1
            if authorization_needs_reconnect(error):
                async with session_maker() as db:
                    user = await db.get(User, user_id, options=[noload("*")])
                    if user is not None:
                        user.google_calendar_connected = False
                        await db.commit()
            logger.warning("Calendar blocks sync failed for user_id=%s (%s)", user_id, type(error).__name__)
    return {"users": len(user_ids), "failed": failed}
