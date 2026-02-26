"""Client Activity Timeline — aggregates communications, tasks, digests, proposals."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Client,
    CommunicationLog,
    Task,
    WeeklyDigest,
    Proposal,
    User,
)
from backend.api.deps import get_current_user, require_module

router = APIRouter(prefix="/api/clients", tags=["activity"])


def _user_name(user: User | None) -> str | None:
    return user.full_name if user else None


@router.get("/{client_id}/activity")
async def get_client_activity(
    client_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Unified chronological activity feed for a client."""
    # Verify client exists
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    events: list[dict] = []

    # 1) Communications
    comms_q = (
        select(CommunicationLog)
        .where(CommunicationLog.client_id == client_id)
        .order_by(desc(CommunicationLog.occurred_at))
        .limit(limit)
    )
    comms = (await db.execute(comms_q)).scalars().all()

    # 2) Tasks completed
    tasks_q = (
        select(Task)
        .where(Task.client_id == client_id, Task.status == "completed")
        .order_by(desc(Task.updated_at))
        .limit(limit)
    )
    completed_tasks = (await db.execute(tasks_q)).scalars().all()

    # 3) Tasks created (recent)
    tasks_created_q = (
        select(Task)
        .where(Task.client_id == client_id)
        .order_by(desc(Task.created_at))
        .limit(limit)
    )
    created_tasks = (await db.execute(tasks_created_q)).scalars().all()

    # 4) Weekly Digests
    digests_q = (
        select(WeeklyDigest)
        .where(WeeklyDigest.client_id == client_id)
        .order_by(desc(WeeklyDigest.created_at))
        .limit(limit)
    )
    digests = (await db.execute(digests_q)).scalars().all()

    # 5) Proposals
    proposals_q = (
        select(Proposal)
        .where(Proposal.client_id == client_id)
        .order_by(desc(Proposal.created_at))
        .limit(limit)
    )
    proposals = (await db.execute(proposals_q)).scalars().all()

    # Batch-load all referenced users in a single query (fix N+1)
    user_ids: set[int] = set()
    for c in comms:
        if c.user_id:
            user_ids.add(c.user_id)
    for t in completed_tasks:
        if t.assigned_to:
            user_ids.add(t.assigned_to)
    for p in proposals:
        if p.created_by:
            user_ids.add(p.created_by)

    users_map: dict[int, User] = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_map = {u.id: u for u in users_result.scalars().all()}

    # Build events from communications
    channel_labels = {
        "email": "Email",
        "call": "Llamada",
        "meeting": "Reunión",
        "whatsapp": "WhatsApp",
        "slack": "Slack",
        "other": "Otro",
    }
    for c in comms:
        direction_label = "entrante" if c.direction.value == "inbound" else "saliente"
        events.append({
            "id": f"comm-{c.id}",
            "type": "communication",
            "subtype": c.channel.value,
            "timestamp": c.occurred_at.isoformat(),
            "title": f"{channel_labels.get(c.channel.value, c.channel.value)} {direction_label}",
            "description": c.subject or c.summary[:120],
            "detail": c.summary,
            "user_name": _user_name(users_map.get(c.user_id)),
            "contact_name": c.contact_name,
            "icon": "message",
        })

    # Build events from completed tasks
    for t in completed_tasks:
        events.append({
            "id": f"task-{t.id}",
            "type": "task_completed",
            "subtype": t.priority.value if t.priority else "medium",
            "timestamp": t.updated_at.isoformat(),
            "title": "Tarea completada",
            "description": t.title,
            "detail": t.description,
            "user_name": _user_name(users_map.get(t.assigned_to)) if t.assigned_to else None,
            "icon": "check",
        })

    # Build events from created tasks
    for t in created_tasks:
        events.append({
            "id": f"task-created-{t.id}",
            "type": "task_created",
            "subtype": t.priority.value if t.priority else "medium",
            "timestamp": t.created_at.isoformat(),
            "title": "Nueva tarea",
            "description": t.title,
            "detail": None,
            "user_name": None,
            "icon": "plus",
        })

    # Build events from digests
    for d in digests:
        status_labels = {"draft": "borrador", "reviewed": "revisado", "sent": "enviado"}
        events.append({
            "id": f"digest-{d.id}",
            "type": "digest",
            "subtype": d.status.value,
            "timestamp": (d.generated_at or d.created_at).isoformat(),
            "title": f"Digest semanal ({status_labels.get(d.status.value, d.status.value)})",
            "description": f"{d.period_start} — {d.period_end}",
            "detail": None,
            "user_name": None,
            "icon": "newspaper",
        })

    # Build events from proposals
    for p in proposals:
        proposal_status_labels = {
            "draft": "borrador",
            "sent": "enviado",
            "accepted": "aceptado",
            "rejected": "rechazado",
            "expired": "expirado",
        }
        events.append({
            "id": f"proposal-{p.id}",
            "type": "proposal",
            "subtype": p.status.value,
            "timestamp": p.created_at.isoformat(),
            "title": f"Presupuesto ({proposal_status_labels.get(p.status.value, p.status.value)})",
            "description": p.title,
            "detail": None,
            "user_name": _user_name(users_map.get(p.created_by)) if p.created_by else None,
            "icon": "file-text",
        })

    # Sort all events by timestamp descending
    events.sort(key=lambda e: e["timestamp"], reverse=True)

    # Apply limit
    return events[:limit]
