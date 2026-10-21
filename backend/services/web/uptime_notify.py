"""Outbox de avisos de caída/recuperación al canal de Slack de cada cliente.

La caída se guarda con ``slack_down_status='pending'`` en la misma transacción
que el estado (``uptime.apply_probe``). Aquí se lee lo pendiente, se publica
SIN transacción abierta y se anota con un UPDATE condicional
(``... WHERE status='pending'``). El job ``uptime`` es único (lock 15), así que
no hay dos repartidores a la vez.

- Enviado → ``sent`` + hora.
- Webhook revocado (404/410) → el aviso queda ``failed`` y el cliente pasa a
  ``slack_enabled=false`` + ``slack_revoked_at``: un admin tiene que poner otro.
- Fallo transitorio → ``slack_attempts += 1``; tras ``MAX_ATTEMPTS`` queda ``failed``.
- Slack apagado o sin webhook cuando toca enviar → ``skipped``.
La recuperación siempre sale después del aviso de caída, nunca sola.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import or_, select, update

from backend.core.security import decrypt_vault_secret
from backend.db.models import Client, ClientWebSettings, WebOutage, WebUptimeTarget
from backend.services.web.slack import post_message
from backend.services.web.uptime import cause_label, format_duration, local_when, slack_eligible

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 10
BATCH = 50


def compose(kind: str, client_name: str, target: WebUptimeTarget, outage: WebOutage) -> tuple[str, list[dict]]:
    where = target.label or target.url
    if kind == "down":
        text = f"La web de {client_name} no responde"
        detail = f"{where} · desde el {local_when(outage.started_at)}"
        cause = cause_label(outage.cause)
        if cause:
            detail += f" · {cause}"
        body = f":red_circle: *{text}*\n{detail}"
    else:
        text = f"La web de {client_name} vuelve a responder"
        body = (
            f":large_green_circle: *{text}*\n{where} · caída de "
            f"{format_duration(outage.ended_at - outage.started_at)} "
            f"(del {local_when(outage.started_at)} al {local_when(outage.ended_at)})"
        )
    return text, [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]


async def _mark(db, outage_id: int, notice: str, values: dict) -> None:
    column = WebOutage.slack_down_status if notice == "down" else WebOutage.slack_recovery_status
    await db.execute(update(WebOutage).where(WebOutage.id == outage_id, column == "pending").values(**values))


def _done(notice: str, status: str, now: datetime | None = None) -> dict:
    prefix = "slack_down" if notice == "down" else "slack_recovery"
    values = {f"{prefix}_status": status}
    if status == "sent":
        values[f"{prefix}_sent_at"] = now
    return values


async def _deliver_notice(session_factory, outage_id: int, post) -> str | None:
    """Envía el siguiente aviso pendiente de una caída. Devuelve qué pasó o None."""
    async with session_factory() as db:
        row = (await db.execute(
            select(WebOutage, WebUptimeTarget, Client.name, ClientWebSettings)
            .join(WebUptimeTarget, WebUptimeTarget.id == WebOutage.target_id)
            .join(Client, Client.id == WebUptimeTarget.client_id)
            .outerjoin(ClientWebSettings, ClientWebSettings.client_id == WebUptimeTarget.client_id)
            .where(WebOutage.id == outage_id)
        )).one_or_none()
        if row is None:
            return None
        outage, target, client_name, web = row
        if outage.slack_down_status == "pending":
            notice = "down"
        elif outage.slack_recovery_status == "pending" and outage.slack_down_status == "sent":
            notice = "recovery"
        elif outage.slack_recovery_status == "pending":
            # El aviso de caída no salió (apagado, fallido…): la recuperación sola no tiene sentido.
            await _mark(db, outage_id, "recovery", _done("recovery", "skipped"))
            await db.commit()
            return "skipped"
        else:
            return None
        if not slack_eligible(web):
            await _mark(db, outage_id, notice, _done(notice, "skipped"))
            await db.commit()
            return "skipped"
        try:
            webhook = decrypt_vault_secret(web.slack_webhook_url)
        except ValueError:
            await _mark(db, outage_id, notice, _done(notice, "failed"))
            await db.commit()
            logger.error("Uptime: no se pudo descifrar el webhook del cliente %s", target.client_id)
            return "failed"
        text, blocks = compose(notice, client_name, target, outage)
        client_id, attempts = target.client_id, outage.slack_attempts or 0
        await db.commit()  # sólo se ha leído: nada de transacción abierta mientras se habla con Slack

    result = await post(webhook, text, blocks)
    now = datetime.now(UTC)
    async with session_factory() as db:
        if result.ok:
            await _mark(db, outage_id, notice, _done(notice, "sent", now))
            outcome = "sent"
        elif result.revoked:
            await _mark(db, outage_id, notice, _done(notice, "failed"))
            await db.execute(update(ClientWebSettings).where(ClientWebSettings.client_id == client_id).values(
                slack_enabled=False, slack_revoked_at=now,
            ))
            outcome = "revoked"
        else:
            values = {"slack_attempts": attempts + 1}
            if attempts + 1 >= MAX_ATTEMPTS:
                values.update(_done(notice, "failed"))
            await _mark(db, outage_id, notice, values)
            outcome = "retry"
        await db.commit()
    return outcome


async def deliver_pending(session_factory, *, post=post_message) -> dict:
    """Publica lo pendiente. Nunca lanza por Slack: devuelve el recuento."""
    totals = {"sent": 0, "skipped": 0, "failed": 0, "revoked": 0, "retry": 0}
    async with session_factory() as db:
        ids = list((await db.execute(
            select(WebOutage.id).where(or_(
                WebOutage.slack_down_status == "pending", WebOutage.slack_recovery_status == "pending",
            )).order_by(WebOutage.id).limit(BATCH)
        )).scalars())
    for outage_id in ids:
        # Hasta dos avisos por caída (caída y recuperación), en orden.
        for _ in range(2):
            try:
                outcome = await _deliver_notice(session_factory, outage_id, post)
            except Exception as exc:  # noqa: BLE001
                logger.error("Uptime: aviso de Slack falló outage_id=%s (%s)", outage_id, type(exc).__name__)
                outcome = None
            if outcome is None:
                break
            totals[outcome] += 1
            if outcome in ("retry", "revoked", "failed"):
                break
    return totals
