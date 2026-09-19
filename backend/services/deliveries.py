"""Durable manual daily/digest delivery. Never call providers before committing intent.

A lease fences database writes, not an in-flight HTTP request. An expired sending
attempt is therefore uncertain and requires human review, not automatic resend.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import noload, selectinload

from backend.config import settings
from backend.core.security import decrypt_vault_secret
from backend.db.models import (
    CommunicationRequest,
    DailyUpdate,
    DailyUpdateStatus,
    Delivery,
    DeliveryAttempt,
    DiscordSettings,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.schemas.daily import ParsedDailyData
from backend.schemas.digest import DigestContent
from backend.services.daily_parser import format_daily_for_discord
from backend.services.digest_renderer import render_discord
from backend.services.temporal import utc_isoformat, utc_now_naive

logger = logging.getLogger(__name__)
LEASE_SECONDS = 90
SOURCE_MODELS = {"daily": DailyUpdate, "digest": WeeklyDigest, "communication": CommunicationRequest}
WEBHOOK_RE = re.compile(r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[^/?#]+$")


class _WebhookLogRedaction(logging.Filter):
    """httpx logs request URLs at INFO; webhook credentials are URL segments."""
    pattern = re.compile(r"(https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/)[^\s?#]+")

    def filter(self, record):
        record.msg = self.pattern.sub(r"\1[redacted]", str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(self.pattern.sub(r"\1[redacted]", str(arg)) if isinstance(arg, (str, httpx.URL)) else arg for arg in record.args)
        return True


logging.getLogger("httpx").addFilter(_WebhookLogRedaction())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


async def authorize_source(db, kind, source_id, actor, *, write=True, lock=False):
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Usuario desactivado o no disponible")
    if kind not in SOURCE_MODELS:
        raise HTTPException(404, "Fuente no encontrada")
    if kind == "digest":
        from backend.services.digest_access import authorize_digest
        return await authorize_digest(db, source_id, actor, write=write, lock=lock)
    model = SOURCE_MODELS[kind]
    stmt = select(model).where(model.id == source_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    source = (await db.execute(stmt)).scalar_one_or_none()
    if not source:
        raise HTTPException(404, "El borrador ya no existe")
    if kind == "communication":
        if source.kind.startswith("scheduled_"):
            from backend.services.scheduled_communications import authorize_scheduled
            await authorize_scheduled(db, source, actor, write=write)
        else:
            from backend.services.manual_communications import authorize_request
            authorize_request(source, actor, write=write)
        return source
    owner = source.user_id if kind == "daily" else source.created_by
    if actor.role != UserRole.admin and owner != actor.id:
        raise HTTPException(403, "No tienes acceso a este borrador")
    return source


def source_version(kind, source):
    if kind == "communication":
        return fingerprint([source.owner_id, source.kind, source.scope, source.period_start,
                            source.period_end, source.title, source.content, source.destination_kind])
    if kind == "daily":
        data = [source.user_id, source.date, source.raw_text, source.parsed_data]
    else:
        data = [source.created_by, source.client_id, source.period_start, source.period_end, source.tone, source.content]
    return fingerprint(data)


async def discord_config(db):
    ds = (await db.execute(select(DiscordSettings).limit(1))).scalar_one_or_none()
    def decrypt(raw):
        return decrypt_vault_secret(raw) if raw and raw.startswith("v1:") else raw
    try:
        url = decrypt(ds.webhook_url) if ds and ds.webhook_url else settings.DISCORD_WEBHOOK_URL
        bot = decrypt(ds.bot_token) if ds and ds.bot_token else None
    except Exception:
        raise HTTPException(400, "No se puede leer la configuración de Discord") from None
    if not url or not WEBHOOK_RE.fullmatch(url):
        raise HTTPException(400, "Configura un webhook válido de Discord antes de enviar")
    return url, bot, fingerprint([url, bool(bot)])


async def destination_config(db, kind, source):
    if kind == "communication" and source.destination_kind == "owner_dm":
        ds = (await db.execute(select(DiscordSettings).limit(1))).scalar_one_or_none()
        try:
            raw = ds.bot_token if ds else None
            bot = decrypt_vault_secret(raw) if raw and raw.startswith("v1:") else raw
        except Exception:
            raise HTTPException(400, "No se puede leer la configuración de Discord") from None
        recipient = settings.DISCORD_OWNER_USER_ID
        if hasattr(source, "destination_id"):
            recipient = source.destination_id
        elif getattr(source, "kind", "") == "scheduled_weekly":
            from backend.db.models import CommunicationOccurrence, CommunicationSchedule
            recipient = await db.scalar(select(CommunicationSchedule.destination_id).join(CommunicationOccurrence,
                CommunicationOccurrence.schedule_id == CommunicationSchedule.id).where(CommunicationOccurrence.request_id == source.id))
        if not bot or not recipient or not recipient.isdigit():
            raise HTTPException(400, "Configura el bot y su destinatario Discord antes de enviar")
        return recipient, bot, fingerprint(["owner_dm", recipient])
    return await discord_config(db)


def render_snapshot(kind, source, custom_content=None):
    if kind == "communication":
        return source.title, source.content
    if kind == "daily":
        name = source.user.full_name
        header = f"{name} — {source.date.isoformat()}"
        try:
            parsed = ParsedDailyData.model_validate(source.parsed_data).model_dump() if source.parsed_data else None
        except Exception:
            parsed = None
        if parsed and not any(parsed.values()):
            parsed = None
        if parsed:
            text = format_daily_for_discord(parsed, name, source.date.isoformat(), max_length=None)
        else:
            text = f"{header}\nSin estructurar\n\n{source.raw_text.strip()}"
    else:
        if not source.content:
            raise HTTPException(400, "El digest no tiene contenido")
        try:
            text = custom_content if custom_content is not None else render_discord(
                DigestContent(**source.content),
                source.tone,
                period_start=source.period_start,
                period_end=source.period_end,
            )
        except Exception:
            raise HTTPException(400, "Contenido del digest malformado") from None
        header = f"Resumen — {source.period_start} a {source.period_end}"
    if not text.strip():
        raise HTTPException(400, "El mensaje está vacío")
    return header, text


def message_chunks(text, limit=1900):
    """Keep Unicode characters intact and stay below UTF-16 character limits."""
    chunk, units = [], 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > limit:
            yield "".join(chunk)
            chunk, units = [], 0
        chunk.append(char)
        units += size
    if chunk:
        yield "".join(chunk)


def plan_steps(kind, header, text, *, threaded):
    steps = []
    if kind == "daily" and threaded:
        steps.extend([
            {"kind": "header", "label": "Cabecera", "content": header},
            {"kind": "thread", "label": "Hilo", "content": next(message_chunks(header, 100))},
        ])
    # Full text is retained, including when AI parsing failed. No truncation.
    for index, chunk in enumerate(message_chunks(text), start=1):
        steps.append({"kind": "body", "label": f"Texto {index}", "content": chunk})
    return [dict(step, status="pending") for step in steps]


async def enqueue(db, kind, source_id, actor, *, custom_content=None):
    delivery = await stage_delivery(db, kind, source_id, actor, custom_content=custom_content)
    await db.commit()
    return delivery


async def stage_delivery(db, kind, source_id, actor, *, custom_content=None):
    """Stage only; caller owns the transaction. No provider effects or commit."""
    source = await authorize_source(db, kind, source_id, actor, lock=True)
    target, bot, destination = await destination_config(db, kind, source)
    version = source_version(kind, source)
    header, text = render_snapshot(kind, source, custom_content)
    key = fingerprint([kind, source_id, version, destination, text])
    existing = (await db.execute(select(Delivery).where(Delivery.dedupe_key == key))).scalar_one_or_none()
    if existing:
        if existing.status in ("cancelled", "expired"):
            existing.actor_id = actor.id
            existing.status, existing.error_code = "pending", None
            existing.available_at = utc_now_naive()
            existing.expires_at = utc_now_naive() + timedelta(days=1)
            existing.message = "En cola tras revisar de nuevo el borrador"
        return existing
    prior = (await db.execute(select(Delivery).where(
        Delivery.source_kind == kind, Delivery.source_id == source_id,
        Delivery.status.in_(["pending", "sending", "uncertain"]),
    ).with_for_update().execution_options(populate_existing=True))).scalars().all()
    for row in prior:
        if row.status == "pending":
            row.status, row.message = "cancelled", "Sustituido por una nueva versión revisada"
        elif row.status == "sending":
            raise HTTPException(409, "Hay un envío en curso. Revisa su recibo antes de enviar otra versión")
        else:
            reviewed = await db.scalar(select(Delivery.id).where(Delivery.resend_of == row.id).limit(1))
            if not reviewed:
                raise HTTPException(409, "Hay un envío incierto. Revisa su recibo antes de reenviar")
    now = utc_now_naive()
    steps = plan_steps("daily" if kind == "communication" and source.kind == "daily_summary" else kind,
                       header, text, threaded=bool(bot))
    if kind == "communication" and source.destination_kind == "owner_dm":
        steps = [{"kind": "dm_channel", "label": "Canal privado", "content": "", "status": "pending"}] + [
            dict(step, kind="dm_body") for step in steps]
    delivery = Delivery(
        id=str(uuid4()), dedupe_key=key, actor_id=actor.id, source_kind=kind,
        source_id=source_id, source_version=version, destination_key=destination,
        payload={"text": text, "steps": steps,
                 "destination_label": f"DM Discord · {target}" if kind == "communication" and source.destination_kind == "owner_dm" else "Canal de Discord del equipo"},
        status="pending", available_at=now, expires_at=now + timedelta(days=1),
        message="En cola para Discord. El borrador está guardado.",
    )
    db.add(delivery)
    await db.flush()
    return delivery


async def latest_attempt(db, delivery_id, *, lock=False):
    stmt = select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id).order_by(DeliveryAttempt.number.desc()).limit(1)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def load_delivery(db, delivery_id, actor, *, write=False, lock=False):
    stmt = select(Delivery).where(Delivery.id == delivery_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Envío no encontrado")
    source = await authorize_source(db, row.source_kind, row.source_id, actor, write=write)
    return row, source


async def receipt(db, row, source, *, writable=True):
    attempt = await latest_attempt(db, row.id)
    changed = source_version(row.source_kind, source) != row.source_version
    return dict(
        delivery_id=row.id, success=row.status == "sent", status=row.status,
        message=row.message or "En cola", source_kind=row.source_kind, source_id=row.source_id,
        source_version=row.source_version, source_changed=changed, content=row.payload["text"],
        created_at=utc_isoformat(row.created_at), sent_at=utc_isoformat(row.sent_at), error_code=row.error_code,
        steps=attempt.steps if attempt else row.payload["steps"],
        can_retry=writable and row.status == "failed" and (not changed or bool(row.resend_of)) and row.error_code in ("rejected", "rate_limit", "not_connected"),
        can_resend=writable and row.status == "uncertain", can_cancel=writable and row.status == "pending",
        worker_enabled=settings.DELIVERY_WORKER_ENABLED,
        **({"title": source.title, "scope": source.scope,
            "period_start": source.period_start.isoformat(), "period_end": source.period_end.isoformat(),
            "destination_label": row.payload.get("destination_label", "Canal de Discord del equipo")}
           if row.source_kind == "communication" else {}),
    )


async def retry(db, row, source):
    if row.status != "failed" or row.error_code not in ("rejected", "rate_limit", "not_connected"):
        raise HTTPException(409, "Este estado no permite reintento seguro")
    if not row.resend_of and source_version(row.source_kind, source) != row.source_version:
        raise HTTPException(409, "El borrador cambió. Envía la versión actual desde su editor")
    row.status, row.error_code, row.message = "pending", None, "Reintento en cola; se conservan las partes confirmadas"
    row.expires_at = utc_now_naive() + timedelta(days=1)
    await db.commit()


async def resend(db, row, source, actor, review_key):
    # The request key also makes repeated clicks/replayed HTTP idempotent.
    key = fingerprint(["reviewed-resend", row.id, actor.id, review_key])
    existing = (await db.execute(select(Delivery).where(Delivery.dedupe_key == key))).scalar_one_or_none()
    if existing:
        return existing
    if row.status != "uncertain":
        raise HTTPException(409, "Solo los envíos inciertos requieren este reenvío revisado")
    if await db.scalar(select(Delivery.id).where(Delivery.resend_of == row.id).limit(1)):
        raise HTTPException(409, "Ya hay un reenvío revisado; consulta su recibo")
    now = utc_now_naive()
    replacement = Delivery(
        id=str(uuid4()), dedupe_key=key, actor_id=actor.id, source_kind=row.source_kind,
        source_id=row.source_id, source_version=row.source_version, destination_key=row.destination_key,
        payload=deepcopy(row.payload), status="pending", available_at=now,
        expires_at=now + timedelta(days=1), resend_of=row.id,
        message="Reenvío revisado en cola. Puede repetir un mensaje ya recibido.",
    )
    db.add(replacement)
    await db.commit()
    return replacement


async def recover_expired(db):
    now = utc_now_naive()
    rows = (await db.execute(select(Delivery).join(DeliveryAttempt, DeliveryAttempt.delivery_id == Delivery.id).where(
        Delivery.status == "sending", DeliveryAttempt.status == "sending", DeliveryAttempt.lease_until <= now,
    ).order_by(DeliveryAttempt.lease_until).with_for_update(of=Delivery, skip_locked=True).execution_options(populate_existing=True).limit(50))).scalars().all()
    for row in rows:
        attempt = await latest_attempt(db, row.id)
        if attempt and attempt.lease_until <= now:
            row.status, row.error_code = "uncertain", "lease_expired"
            row.message = "Se perdió la confirmación del envío. Comprueba Discord antes de reenviar."
            attempt.status = "uncertain"
    await db.commit()


async def claim(db):
    now = utc_now_naive()
    row = (await db.execute(select(Delivery).where(
        Delivery.status == "pending", Delivery.available_at <= now,
    ).order_by(Delivery.available_at, Delivery.id).with_for_update(skip_locked=True).execution_options(populate_existing=True).limit(1))).scalar_one_or_none()
    if not row:
        await db.commit()
        return None
    if row.expires_at <= now:
        row.status, row.message = "expired", "El envío caducó. Revisa el borrador antes de volver a enviarlo."
        await db.commit()
        return None
    actor = (await db.execute(select(User).where(User.id == row.actor_id).options(selectinload(User.permissions), noload(User.tasks)))).scalar_one_or_none()
    try:
        source = await authorize_source(db, row.source_kind, row.source_id, actor)
        if not row.resend_of and source_version(row.source_kind, source) != row.source_version:
            raise HTTPException(409, "El borrador cambió antes de enviar. Revisa la versión actual")
        url, bot, destination = await destination_config(db, row.source_kind, source)
        if destination != row.destination_key:
            raise HTTPException(409, "El destino cambió. Revisa la configuración antes de enviar")
    except HTTPException as exc:
        row.status, row.error_code, row.message = "cancelled", "preflight", str(exc.detail)
        await db.commit()
        return None
    from backend.services.scheduled_communications import defer_delivery
    if await defer_delivery(db, row, source):
        return None
    previous = await latest_attempt(db, row.id)
    steps = deepcopy(previous.steps if previous else row.payload["steps"])
    for step in steps:
        if step["status"] != "sent":
            step["status"] = "pending"
            step.pop("error", None)
    attempt = DeliveryAttempt(
        id=str(uuid4()), delivery_id=row.id, number=previous.number + 1 if previous else 1,
        status="sending", lease_until=now + timedelta(seconds=LEASE_SECONDS), steps=steps,
    )
    row.status, row.message = "sending", "Enviando a Discord"
    db.add(attempt)
    await db.commit()
    return row.id, attempt.id, url, bot


class SendFailure(Exception):
    def __init__(self, code, message, *, uncertain=False, retry_after=0):
        self.code, self.message, self.uncertain, self.retry_after = code, message, uncertain, retry_after


async def send_step(http, url, bot, step, steps):
    if step["kind"] == "dm_channel":
        target = "https://discord.com/api/v10/users/@me/channels"
        body, headers = {"recipient_id": url}, {"Authorization": f"Bot {bot}"}
    elif step["kind"] == "dm_body":
        channel = next(s for s in steps if s["kind"] == "dm_channel").get("channel_id")
        if not channel:
            raise SendFailure("missing_receipt", "El canal privado no tiene confirmación", uncertain=True)
        target = f"https://discord.com/api/v10/channels/{channel}/messages"
        body, headers = {"content": step["content"], "allowed_mentions": {"parse": []}}, {"Authorization": f"Bot {bot}"}
    elif step["kind"] == "thread":
        header = next(s for s in steps if s["kind"] == "header")
        channel, message = header.get("channel_id"), header.get("message_id")
        if not channel or not message:
            raise SendFailure("missing_receipt", "La cabecera no tiene recibo completo", uncertain=True)
        target = f"https://discord.com/api/v10/channels/{channel}/messages/{message}/threads"
        body, headers = {"name": step["content"]}, {"Authorization": f"Bot {bot}"}
    else:
        target = url + "?wait=true"
        thread = next((s for s in steps if s["kind"] == "thread"), None)
        if step["kind"] == "body" and thread:
            target += "&thread_id=" + thread["message_id"]
        body, headers = {"content": step["content"], "allowed_mentions": {"parse": []}}, {}
    try:
        response = await http.post(target, json=body, headers=headers)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise SendFailure("not_connected", "No se pudo conectar con Discord") from None
    except Exception:
        raise SendFailure("response_lost", "No se pudo confirmar si Discord recibió esta parte", uncertain=True) from None
    if response.status_code == 429:
        try:
            delay = min(86400, max(1, float(response.json().get("retry_after", 60))))
        except Exception:
            delay = 60
        raise SendFailure("rate_limit", "Discord ha pedido esperar antes de reintentar", retry_after=delay)
    if 400 <= response.status_code < 500:
        raise SendFailure("rejected", f"Discord rechazó esta parte (HTTP {response.status_code})")
    if response.status_code not in (200, 201):
        raise SendFailure("provider_uncertain", "Discord no confirmó la entrega", uncertain=True)
    try:
        data = response.json()
        message_id = str(data["id"])
        if not message_id.isdigit():
            raise ValueError()
        channel_id = str(data.get("channel_id", ""))
    except Exception:
        raise SendFailure("missing_receipt", "Discord respondió sin un ID de confirmación válido", uncertain=True) from None
    if step["kind"] == "dm_channel":
        return {"channel_id": message_id}  # A channel is not a sent message.
    return {"message_id": message_id, "channel_id": channel_id if channel_id.isdigit() else None}


async def _locked_attempt(db, delivery_id, attempt_id):
    # Enqueue locks source -> intent. Keep that order here too, including the
    # final version check, so an edit/new enqueue cannot deadlock finalization.
    known = await db.get(Delivery, delivery_id)
    if not known:
        return None, None
    model = SOURCE_MODELS.get(known.source_kind)
    if model is None:
        return None, None
    await db.execute(select(model.id).where(model.id == known.source_id).with_for_update())
    row = await db.scalar(select(Delivery).where(Delivery.id == delivery_id).with_for_update().execution_options(populate_existing=True))
    attempt = await latest_attempt(db, delivery_id, lock=True)
    if not row or row.status != "sending" or not attempt or attempt.id != attempt_id or attempt.lease_until <= utc_now_naive():
        return None, None
    return row, attempt


async def dispatch_claim(session_factory, claimed, *, transport=None):
    delivery_id, attempt_id, url, bot = claimed
    async with httpx.AsyncClient(timeout=15, transport=transport) as http:
        while True:
            async with session_factory() as db:
                row, attempt = await _locked_attempt(db, delivery_id, attempt_id)
                if row is None:
                    return
                steps = deepcopy(attempt.steps)
                index = next((i for i, step in enumerate(steps) if step["status"] != "sent"), None)
                if index is None:
                    # Lock/reload source before marking the current version sent.
                    if row.source_kind == "daily":
                        source = await db.scalar(select(DailyUpdate).where(DailyUpdate.id == row.source_id).with_for_update())
                        if source and source_version("daily", source) == row.source_version:
                            source.status = DailyUpdateStatus.sent
                            source.discord_sent_at = utc_now_naive()
                    row.status, row.sent_at, row.error_code, row.message = "sent", utc_now_naive(), None, "Enviado a Discord"
                    attempt.status = "sent"
                    await db.commit()
                    return
                actor = (await db.execute(select(User).where(User.id == row.actor_id).options(selectinload(User.permissions), noload(User.tasks)))).scalar_one_or_none()
                try:
                    source = await authorize_source(db, row.source_kind, row.source_id, actor)
                    if not row.resend_of and source_version(row.source_kind, source) != row.source_version:
                        raise HTTPException(409, "El borrador cambió; no se enviarán más partes")
                    url, bot, destination = await destination_config(db, row.source_kind, source)
                    if destination != row.destination_key:
                        raise HTTPException(409, "El destino cambió; no se enviarán más partes")
                except HTTPException as exc:
                    row.status, row.error_code, row.message = "cancelled", "preflight", str(exc.detail)
                    attempt.status = "cancelled"
                    await db.commit()
                    return
                from backend.services.scheduled_communications import defer_delivery
                if await defer_delivery(db, row, source, attempt):
                    return
                steps[index]["status"] = "sending"
                steps[index]["started_at"] = utc_isoformat(utc_now_naive())
                attempt.steps, attempt.lease_until = steps, utc_now_naive() + timedelta(seconds=LEASE_SECONDS)
                await db.commit()  # durable marker BEFORE each external effect
                if attempt.lease_until <= utc_now_naive():
                    return  # a delayed commit must not start HTTP with an expired lease
            outcome, failure = None, None
            try:
                outcome = await send_step(http, url, bot, steps[index], steps)
            except SendFailure as exc:
                failure = exc
            async with session_factory() as db:
                row, attempt = await _locked_attempt(db, delivery_id, attempt_id)
                if row is None:
                    # Preserve a late provider receipt on its original attempt,
                    # without reviving the lease or changing delivery state.
                    if outcome:
                        original = await db.scalar(select(DeliveryAttempt).where(
                            DeliveryAttempt.id == attempt_id, DeliveryAttempt.delivery_id == delivery_id,
                        ).with_for_update())
                        if original and original.steps[index]["status"] != "sent":
                            old_steps = deepcopy(original.steps)
                            old_steps[index].update(status="sent", **outcome, confirmed_at=utc_isoformat(utc_now_naive()))
                            original.steps = old_steps
                            await db.commit()
                    return  # a late response cannot overwrite a recovered attempt
                steps = deepcopy(attempt.steps)
                if failure:
                    state = "uncertain" if failure.uncertain else "failed"
                    steps[index].update(status=state, error=failure.message)
                    row.status, row.error_code, row.message = state, failure.code, failure.message
                    row.available_at = utc_now_naive() + timedelta(seconds=failure.retry_after)
                    attempt.status = state
                else:
                    steps[index].update(status="sent", **outcome)
                    steps[index]["confirmed_at"] = utc_isoformat(utc_now_naive())
                attempt.steps = steps
                # If this fails, no more HTTP occurs. Lease recovery exposes
                # uncertainty rather than replaying a potentially accepted send.
                await db.commit()
                if failure:
                    return


async def run_once(session_factory, *, transport=None):
    async with session_factory() as db:
        await recover_expired(db)
        claimed = await claim(db)
    if claimed:
        await dispatch_claim(session_factory, claimed, transport=transport)
    return bool(claimed)


async def delivery_loop():
    import asyncio

    from backend.db.database import async_session
    while True:
        try:
            worked = await run_once(async_session)
        except Exception as exc:
            # No URL/token/raw provider exception in logs.
            logger.error("Delivery worker failed (%s); in-flight receipts require recovery", type(exc).__name__)
            worked = False
        await asyncio.sleep(0 if worked else 5)
