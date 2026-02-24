"""Weekly Digests API endpoints.

Endpoints:
- POST /generate          — generate a new digest for one client
- POST /generate-batch    — generate digests for all active clients
- GET  /                  — list digests (filterable)
- GET  /{id}              — get single digest
- PUT  /{id}              — update digest content/tone
- PATCH /{id}/status      — change digest status
- GET  /{id}/render       — render digest as Slack or Email HTML
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    WeeklyDigest, DigestStatus, DigestTone, Client, ClientStatus, User, UserRole,
)
from backend.schemas.digest import (
    DigestGenerateRequest,
    DigestUpdateRequest,
    DigestStatusUpdate,
    DigestResponse,
    DigestContent,
    DigestRenderResponse,
)
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_generator import generate_digest_content
from backend.services.digest_renderer import render_slack, render_email
from backend.api.deps import require_module

router = APIRouter(prefix="/api/digests", tags=["digests"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_period() -> tuple[date, date]:
    """Return (Monday, Sunday) of the previous week."""
    today = date.today()
    # Last Monday
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def _to_response(digest: WeeklyDigest) -> DigestResponse:
    """Convert ORM model to response schema."""
    content = None
    if digest.content:
        try:
            content = DigestContent(**digest.content)
        except Exception:
            content = None

    return DigestResponse(
        id=digest.id,
        client_id=digest.client_id,
        client_name=digest.client.name if digest.client else None,
        period_start=digest.period_start,
        period_end=digest.period_end,
        status=digest.status,
        tone=digest.tone,
        content=content,
        raw_context=digest.raw_context,
        generated_at=digest.generated_at,
        edited_at=digest.edited_at,
        created_by=digest.created_by,
        creator_name=digest.creator.full_name if digest.creator else None,
        created_at=digest.created_at,
        updated_at=digest.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /generate — Generate a new digest for one client
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=DigestResponse)
async def generate_digest(
    request: DigestGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Generate a weekly digest for a single client."""
    period_start = request.period_start
    period_end = request.period_end

    if not period_start or not period_end:
        period_start, period_end = _default_period()

    # Validate client exists
    client_result = await db.execute(select(Client).where(Client.id == request.client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Collect raw data
    raw_data = await collect_digest_data(db, request.client_id, period_start, period_end)

    # Generate content via Claude API
    try:
        content = await generate_digest_content(raw_data, request.tone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create digest record
    digest = WeeklyDigest(
        client_id=request.client_id,
        period_start=period_start,
        period_end=period_end,
        status=DigestStatus.draft,
        tone=request.tone,
        content=content,
        raw_context=raw_data,
        generated_at=datetime.now(timezone.utc),
        created_by=current_user.id,
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)

    return _to_response(digest)


# ---------------------------------------------------------------------------
# POST /generate-batch — Generate digests for all active clients
# ---------------------------------------------------------------------------

@router.post("/generate-batch", response_model=list[DigestResponse])
async def generate_batch(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    tone: DigestTone = DigestTone.cercano,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Generate digests for all active clients at once."""
    if not period_start or not period_end:
        period_start, period_end = _default_period()

    # Get all active clients
    result = await db.execute(
        select(Client).where(Client.status == ClientStatus.active)
    )
    clients = result.scalars().all()

    if not clients:
        raise HTTPException(status_code=404, detail="No active clients found")

    digests = []
    errors = []

    for client in clients:
        try:
            raw_data = await collect_digest_data(db, client.id, period_start, period_end)
            content = await generate_digest_content(raw_data, tone)

            digest = WeeklyDigest(
                client_id=client.id,
                period_start=period_start,
                period_end=period_end,
                status=DigestStatus.draft,
                tone=tone,
                content=content,
                raw_context=raw_data,
                generated_at=datetime.now(timezone.utc),
                created_by=current_user.id,
            )
            db.add(digest)
            digests.append(digest)
        except Exception as e:
            errors.append({"client_id": client.id, "client_name": client.name, "error": str(e)})

    if digests:
        await db.commit()
        for d in digests:
            await db.refresh(d)

    return [_to_response(d) for d in digests]


# ---------------------------------------------------------------------------
# GET / — List digests
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DigestResponse])
async def list_digests(
    client_id: Optional[int] = Query(None),
    status: Optional[DigestStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    """List digests with optional filters."""
    query = select(WeeklyDigest)

    if client_id:
        query = query.where(WeeklyDigest.client_id == client_id)
    if status:
        query = query.where(WeeklyDigest.status == status)
    # Members only see their own digests
    if current_user.role != UserRole.admin:
        query = query.where(WeeklyDigest.created_by == current_user.id)

    query = query.order_by(WeeklyDigest.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)

    return [_to_response(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# GET /{id} — Get single digest
# ---------------------------------------------------------------------------

@router.get("/{digest_id}", response_model=DigestResponse)
async def get_digest(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    """Get a specific digest by ID."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    return _to_response(digest)


# ---------------------------------------------------------------------------
# PUT /{id} — Update digest content/tone
# ---------------------------------------------------------------------------

@router.put("/{digest_id}", response_model=DigestResponse)
async def update_digest(
    digest_id: int,
    request: DigestUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Update a digest's content and/or tone."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    if request.content is not None:
        digest.content = request.content.model_dump()
        digest.edited_at = datetime.now(timezone.utc)
    if request.tone is not None:
        digest.tone = request.tone

    await db.commit()
    await db.refresh(digest)

    return _to_response(digest)


# ---------------------------------------------------------------------------
# PATCH /{id}/status — Change digest status
# ---------------------------------------------------------------------------

@router.patch("/{digest_id}/status", response_model=DigestResponse)
async def update_digest_status(
    digest_id: int,
    request: DigestStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Update a digest's status (draft → reviewed → sent)."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    digest.status = request.status
    await db.commit()
    await db.refresh(digest)

    return _to_response(digest)


# ---------------------------------------------------------------------------
# GET /{id}/render — Render digest as Slack or Email
# ---------------------------------------------------------------------------

@router.get("/{digest_id}/render", response_model=DigestRenderResponse)
async def render_digest(
    digest_id: int,
    format: str = Query("slack", pattern="^(slack|email)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    """Render a digest in the specified format (slack or email)."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    if not digest.content:
        raise HTTPException(status_code=400, detail="Digest has no content to render")

    try:
        content = DigestContent(**digest.content)
    except Exception:
        raise HTTPException(status_code=400, detail="Digest content is malformed")

    if format == "slack":
        rendered = render_slack(content)
    else:
        rendered = render_email(content)

    return DigestRenderResponse(format=format, rendered=rendered)
