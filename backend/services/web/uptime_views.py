"""Lecturas del monitor de caídas: lo que pintan la ficha, la página /web y el
estado del cliente. Nada de esto escribe."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import aliased

from backend.db.models import WebOutage, WebUptimeProbe, WebUptimeState, WebUptimeTarget
from backend.services.temporal import business_zone
from backend.services.web.uptime import cause_label, local_when

RECENT_OUTAGES = 5
# Peor primero: lo que más pide mirar manda en el resumen del cliente.
_RANK = {"down": 5, "blocked": 4, "suspect": 3, "up": 2, "unknown": 1, "paused": 0}


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


async def uptime_pct(db, target_ids: list[int], since: datetime) -> dict[int, float | None]:
    """% de comprobaciones buenas desde ``since``. Un bloqueo no cuenta ni a favor
    ni en contra (no sabemos si estaba arriba)."""
    if not target_ids:
        return {}
    rows = (await db.execute(
        select(
            WebUptimeProbe.target_id,
            func.count().filter(WebUptimeProbe.outcome == "up"),
            func.count().filter(WebUptimeProbe.outcome == "down"),
        ).where(WebUptimeProbe.target_id.in_(target_ids), WebUptimeProbe.checked_at >= since)
        .group_by(WebUptimeProbe.target_id)
    )).all()
    out: dict[int, float | None] = {tid: None for tid in target_ids}
    for target_id, up, down in rows:
        out[target_id] = round(up * 100 / (up + down), 2) if up + down else None
    return out


def outage_view(outage: WebOutage, now: datetime) -> dict:
    end = outage.ended_at or now
    return {
        "id": outage.id,
        "target_id": outage.target_id,
        "kind": outage.kind,
        "started_at": iso(outage.started_at),
        "confirmed_at": iso(outage.confirmed_at),
        "ended_at": iso(outage.ended_at),
        "duration_minutes": max(0, int((end - outage.started_at).total_seconds() // 60)),
        "cause": outage.cause,
        "cause_label": cause_label(outage.cause),
        "status_code": outage.status_code,
        "slack_down_status": outage.slack_down_status,
        "slack_recovery_status": outage.slack_recovery_status,
    }


async def target_views(db, targets: list[WebUptimeTarget], *, recent: bool = True) -> list[dict]:
    """Objetivos con su estado, % de 24 h y 30 días y las últimas caídas."""
    now = datetime.now(UTC)
    ids = [t.id for t in targets]
    if not ids:
        return []
    states = {s.target_id: s for s in (await db.scalars(
        select(WebUptimeState).where(WebUptimeState.target_id.in_(ids))
    )).all()}
    day = await uptime_pct(db, ids, now - timedelta(hours=24))
    month = await uptime_pct(db, ids, now - timedelta(days=30))
    open_outages = {o.target_id: o for o in (await db.scalars(
        select(WebOutage).where(WebOutage.target_id.in_(ids), WebOutage.ended_at.is_(None))
    )).all()}
    recent_by_target: dict[int, list[dict]] = {i: [] for i in ids}
    if recent:
        ranked = select(
            WebOutage, func.row_number().over(
                partition_by=WebOutage.target_id, order_by=WebOutage.started_at.desc(),
            ).label("rn"),
        ).where(WebOutage.target_id.in_(ids)).subquery()
        outage_alias = aliased(WebOutage, ranked)
        for outage in (await db.scalars(
            select(outage_alias).where(ranked.c.rn <= RECENT_OUTAGES).order_by(ranked.c.started_at.desc())
        )).all():
            recent_by_target[outage.target_id].append(outage_view(outage, now))
    out = []
    for target in targets:
        state = states.get(target.id)
        status = (state.status if state else "unknown") if target.is_active else "paused"
        open_outage = open_outages.get(target.id)
        out.append({
            "id": target.id,
            "client_id": target.client_id,
            "url": target.url,
            "label": target.label,
            "is_active": target.is_active,
            "status": status,
            "status_since": iso(state.status_since) if state else None,
            "last_checked_at": iso(state.last_checked_at) if state else None,
            "last_status_code": state.last_status_code if state else None,
            "last_error": state.last_error if state else None,
            "last_error_label": cause_label(state.last_error) if state else None,
            "last_response_ms": state.last_response_ms if state else None,
            "uptime_24h": day.get(target.id),
            "uptime_30d": month.get(target.id),
            "open_outage": outage_view(open_outage, now) if open_outage else None,
            "recent_outages": recent_by_target.get(target.id, []),
        })
    return out


def worst_status(statuses: list[str]) -> str | None:
    return max(statuses, key=lambda s: _RANK.get(s, 0)) if statuses else None


async def client_blocks(db, client_ids: list[int]) -> dict[int, dict]:
    """Resumen por cliente para su estado: peor objetivo y caída abierta más grave.

    Sólo objetivos activos. Un cliente sin objetivos no aparece."""
    if not client_ids:
        return {}
    rows = (await db.execute(
        select(WebUptimeTarget.client_id, WebUptimeTarget.id, WebUptimeState.status, WebUptimeState.last_checked_at)
        .outerjoin(WebUptimeState, WebUptimeState.target_id == WebUptimeTarget.id)
        .where(WebUptimeTarget.client_id.in_(client_ids), WebUptimeTarget.is_active.is_(True))
    )).all()
    outages = (await db.execute(
        select(WebUptimeTarget.client_id, WebOutage.kind, WebOutage.started_at)
        .join(WebUptimeTarget, WebUptimeTarget.id == WebOutage.target_id)
        .where(WebUptimeTarget.client_id.in_(client_ids), WebUptimeTarget.is_active.is_(True),
               WebOutage.ended_at.is_(None))
    )).all()
    blocks: dict[int, dict] = {}
    for client_id, _target_id, status, checked in rows:
        block = blocks.setdefault(client_id, {
            "targets": 0, "statuses": [], "last_checked_at": None,
            "down_since": None, "blocked_since": None,
        })
        block["targets"] += 1
        block["statuses"].append(status or "unknown")
        if checked and (block["last_checked_at"] is None or checked > block["last_checked_at"]):
            block["last_checked_at"] = checked
    for client_id, kind, started in outages:
        block = blocks.get(client_id)
        if block is None:
            continue
        key = "down_since" if kind == "down" else "blocked_since"
        if block[key] is None or started < block[key]:
            block[key] = started
    out = {}
    for client_id, block in blocks.items():
        out[client_id] = {
            "status": worst_status(block.pop("statuses")),
            "targets": block["targets"],
            "alert": "down" if block["down_since"] else "blocked" if block["blocked_since"] else None,
            "down_since": iso(block["down_since"]),
            "blocked_since": iso(block["blocked_since"]),
            "last_checked_at": iso(block["last_checked_at"]),
        }
    return out


def status_reason(block: dict) -> tuple[str, str] | None:
    """(nivel, motivo) para el estado del cliente; None si no hay nada que decir."""
    if block["alert"] == "down":
        since = datetime.fromisoformat(block["down_since"])
        return "act", f"La web no responde desde el {local_when(since)}"
    if block["alert"] == "blocked":
        return "watch", "No podemos comprobar la web (bloqueo)"
    return None


async def daily_history(db, target_id: int, days: int) -> list[dict]:
    """Comprobaciones por día civil (hora de la agencia) de los últimos ``days`` días."""
    zone = business_zone().key
    since = datetime.now(UTC) - timedelta(days=days)
    local_day = cast(func.timezone(zone, WebUptimeProbe.checked_at), Date)
    rows = (await db.execute(
        select(
            local_day.label("day"),
            func.count().filter(WebUptimeProbe.outcome == "up"),
            func.count().filter(WebUptimeProbe.outcome == "down"),
            func.count().filter(WebUptimeProbe.outcome == "blocked"),
            func.avg(WebUptimeProbe.response_ms).filter(WebUptimeProbe.outcome == "up"),
        ).where(WebUptimeProbe.target_id == target_id, WebUptimeProbe.checked_at >= since)
        .group_by(local_day).order_by(local_day)
    )).all()
    out = []
    for day, up, down, blocked, avg_ms in rows:
        out.append({
            "date": day.isoformat() if isinstance(day, date) else str(day),
            "up": up, "down": down, "blocked": blocked,
            "uptime_pct": round(up * 100 / (up + down), 2) if up + down else None,
            "avg_response_ms": int(avg_ms) if avg_ms is not None else None,
        })
    return out
