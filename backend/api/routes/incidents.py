"""Read-only operational inbox and explicit, revisioned recipient decisions."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Notification, User
from backend.schemas.incident import IncidentDecision, IncidentListResponse, IncidentResponse
from backend.services.incidents import decide_incident, incident_response, visible_incident_clause

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    state: Literal["active", "snoozed", "resolved", "dismissed"] = "active",
    cursor: int | None = Query(None, ge=1),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Notification).options(noload("*")).where(
        visible_incident_clause(user.id, current_only=state != "resolved"), Notification.incident_state == state,
    )
    if cursor is not None:
        query = query.where(Notification.id < cursor)
    rows = (await db.execute(query.order_by(Notification.id.desc()).limit(limit + 1))).scalars().all()
    return IncidentListResponse(
        items=[incident_response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/count")
async def incident_count(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    count = await db.scalar(select(func.count(Notification.id)).where(
        visible_incident_clause(user.id, current_only=True), Notification.incident_state == "active",
    ))
    return {"count": count or 0}


@router.post("/{incident_id}/decision", response_model=IncidentResponse)
async def incident_decision(
    incident_id: int, request: IncidentDecision,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    try:
        response = await decide_incident(db, user.id, incident_id, request)
    except HTTPException as exc:
        if exc.status_code == 409:
            # Preserve reconciliation of a concurrently changed source so the
            # conflict's current state is the same state a follow-up GET sees.
            await db.commit()
        raise
    await db.commit()
    return response
