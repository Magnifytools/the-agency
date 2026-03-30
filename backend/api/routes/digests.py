"""Weekly Digests API endpoints.

Endpoints:
- POST /generate          — generate a new digest for one client
- POST /generate-batch    — generate digests for all active clients
- GET  /                  — list digests (filterable)
- GET  /{id}              — get single digest
- PUT  /{id}              — update digest content/tone
- PATCH /{id}/status      — change digest status
- GET  /{id}/render       — render digest as Slack or Email HTML
- DELETE /{id}            — delete a digest (draft or admin)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from backend.services.digest_renderer import render_slack, render_email, render_email_plain, render_discord
from backend.api.deps import require_module
from backend.core.rate_limiter import ai_limiter
from backend.api.utils.db_helpers import safe_refresh
from backend.api.middleware.audit_log import log_audit

router = APIRouter(prefix="/api/digests", tags=["digests"])
logger = logging.getLogger(__name__)


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
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)

    period_start = request.period_start
    period_end = request.period_end

    if not period_start or not period_end:
        period_start, period_end = _default_period()

    # Validate client exists
    client_result = await db.execute(select(Client).where(Client.id == request.client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Auto-delete previous draft digests for this client
    prev_drafts_result = await db.execute(
        select(WeeklyDigest).where(
            and_(
                WeeklyDigest.client_id == request.client_id,
                WeeklyDigest.status == DigestStatus.draft,
            )
        )
    )
    prev_drafts = prev_drafts_result.scalars().all()
    for old_draft in prev_drafts:
        logger.info(
            "Auto-deleting previous draft digest id=%s for client_id=%s",
            old_draft.id,
            request.client_id,
        )
        await db.delete(old_draft)

    # Collect raw data
    raw_data = await collect_digest_data(db, request.client_id, period_start, period_end)

    # Generate content via Claude API
    try:
        content = await generate_digest_content(raw_data, request.tone)
    except ValueError:
        raise HTTPException(status_code=400, detail="No se pudo generar el digest con los datos proporcionados")
    except Exception:
        logger.exception("Unexpected error generating digest for client_id=%s", request.client_id)
        raise HTTPException(status_code=502, detail="Error generando digest")

    # Create digest record
    digest = WeeklyDigest(
        client_id=request.client_id,
        period_start=period_start,
        period_end=period_end,
        status=DigestStatus.draft,
        tone=request.tone,
        content=content,
        raw_context=raw_data,
        generated_at=datetime.utcnow(),
        created_by=current_user.id,
    )
    db.add(digest)
    await db.commit()
    await safe_refresh(db, digest, log_context="digests")

    log_audit(current_user.id, "generate", "digest", digest.id, details=f"client_id={request.client_id}")
    # Reload with relationships for response
    result = await db.execute(
        select(WeeklyDigest).where(WeeklyDigest.id == digest.id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
    return _to_response(result.scalar_one())


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
    ai_limiter.check(current_user.id, max_requests=3, window_seconds=60)

    if not period_start or not period_end:
        period_start, period_end = _default_period()

    # Get all active clients
    result = await db.execute(
        select(Client).where(Client.status == ClientStatus.active)
    )
    clients = result.scalars().all()

    if not clients:
        raise HTTPException(status_code=404, detail="No active clients found")

    # Auto-delete previous draft digests for all active clients
    for client in clients:
        prev_drafts_result = await db.execute(
            select(WeeklyDigest).where(
                and_(
                    WeeklyDigest.client_id == client.id,
                    WeeklyDigest.status == DigestStatus.draft,
                )
            )
        )
        prev_drafts = prev_drafts_result.scalars().all()
        for old_draft in prev_drafts:
            logger.info(
                "Auto-deleting previous draft digest id=%s for client_id=%s (batch)",
                old_draft.id,
                client.id,
            )
            await db.delete(old_draft)

    # Collect data sequentially (shares DB session), then generate AI content concurrently
    client_data: list[tuple] = []
    for client in clients:
        try:
            raw_data = await collect_digest_data(db, client.id, period_start, period_end)
            client_data.append((client, raw_data))
        except Exception:
            logger.exception("Batch data collection failed for client_id=%s", client.id)

    sem = asyncio.Semaphore(5)

    async def _generate(raw_data: dict) -> dict:
        async with sem:
            return await generate_digest_content(raw_data, tone)

    ai_results = await asyncio.gather(
        *[_generate(raw_data) for _, raw_data in client_data],
        return_exceptions=True,
    )

    digests = []
    for (client, raw_data), result in zip(client_data, ai_results):
        if isinstance(result, Exception):
            logger.exception("Batch digest generation failed for client_id=%s: %s", client.id, result)
            continue
        digest = WeeklyDigest(
            client_id=client.id,
            period_start=period_start,
            period_end=period_end,
            status=DigestStatus.draft,
            tone=tone,
            content=result,
            raw_context=raw_data,
            generated_at=datetime.utcnow(),
            created_by=current_user.id,
        )
        db.add(digest)
        digests.append(digest)

    if digests:
        await db.commit()
        for d in digests:
            await safe_refresh(db, d, log_context="digests")

        # Notify creator that batch is done
        try:
            from backend.services.notification_service import create_notification, DIGEST_GENERATED
            await create_notification(
                db,
                user_id=current_user.id,
                type=DIGEST_GENERATED,
                title=f"Batch de digests generado",
                message=f"{len(digests)} digests creados para {period_start} — {period_end}",
                link_url="/digests",
                entity_type="digest",
                entity_id=None,
            )
            await db.commit()
        except Exception as e:
            logger.debug("Notification for batch digest generation failed (never break digest generation): %s", e)
            pass  # Notification failure should never break digest generation

    # Reload with relationships for response
    if digests:
        digest_ids = [d.id for d in digests]
        reload_result = await db.execute(
            select(WeeklyDigest).where(WeeklyDigest.id.in_(digest_ids))
            .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
        )
        digests = reload_result.scalars().all()
    return [_to_response(d) for d in digests]


# ---------------------------------------------------------------------------
# GET / — List digests
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DigestResponse])
async def list_digests(
    client_id: Optional[int] = Query(None),
    status: Optional[DigestStatus] = Query(None),
    period_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    period_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
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
    if period_from:
        query = query.where(WeeklyDigest.period_start >= period_from)
    if period_to:
        query = query.where(WeeklyDigest.period_end <= period_to)
    # Members only see their own digests
    if current_user.role != UserRole.admin:
        query = query.where(WeeklyDigest.created_by == current_user.id)

    query = query.options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
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
    result = await db.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.id == digest_id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
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
    """Update a digest's content and/or tone.

    If only the tone changes (no content update), auto-regenerate
    the digest content using the new tone and the stored raw_context.
    """
    result = await db.execute(
        select(WeeklyDigest).where(WeeklyDigest.id == digest_id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    tone_changed = request.tone is not None and request.tone != digest.tone

    if request.content is not None:
        digest.content = request.content.model_dump()
        digest.edited_at = datetime.utcnow()

    if request.tone is not None:
        digest.tone = request.tone

    # If tone changed without an explicit content update, regenerate content
    if tone_changed and request.content is None:
        if not digest.raw_context:
            raise HTTPException(
                status_code=400,
                detail="No hay datos crudos para regenerar el digest con el nuevo tono",
            )
        ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)
        try:
            new_content = await generate_digest_content(digest.raw_context, request.tone)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="No se pudo regenerar el digest con el nuevo tono",
            )
        except Exception:
            logger.exception("Error regenerating digest id=%s with new tone=%s", digest_id, request.tone)
            raise HTTPException(status_code=502, detail="Error regenerando digest con nuevo tono")
        digest.content = new_content
        digest.generated_at = datetime.utcnow()

    await db.commit()
    await safe_refresh(db, digest, log_context="digests")

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
    result = await db.execute(
        select(WeeklyDigest).where(WeeklyDigest.id == digest_id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")

    digest.status = request.status
    await db.commit()
    await safe_refresh(db, digest, log_context="digests")

    return _to_response(digest)


# ---------------------------------------------------------------------------
# GET /{id}/render — Render digest as Slack or Email
# ---------------------------------------------------------------------------

@router.get("/{digest_id}/render", response_model=DigestRenderResponse)
async def render_digest(
    digest_id: int,
    format: str = Query("slack", pattern="^(slack|email|email_plain|discord)$"),
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

    tone = digest.tone if digest.tone else None

    if format == "slack":
        rendered = render_slack(content, tone=tone)
    elif format == "discord":
        rendered = render_discord(content, tone=tone)
    elif format == "email_plain":
        rendered = render_email_plain(content, tone=tone)
    else:
        rendered = render_email(content, tone=tone)

    return DigestRenderResponse(format=format, rendered=rendered)


# ---------------------------------------------------------------------------
# POST /{id}/send-email — Send digest via email
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _EmailBase

class DigestSendEmailRequest(_EmailBase):
    to: str
    test: bool = False


@router.post("/{digest_id}/send-email")
async def send_digest_email(
    digest_id: int,
    body: DigestSendEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Send a digest to a client via email."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    if current_user.role != UserRole.admin and digest.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not your digest")
    if not digest.content:
        raise HTTPException(status_code=400, detail="Digest has no content")

    try:
        content = DigestContent(**digest.content)
    except Exception:
        raise HTTPException(status_code=400, detail="Digest content is malformed")

    # Render as email HTML + plain text
    tone = digest.tone if digest.tone else None
    html_body = render_email(content, tone=tone)
    plain_body = render_email_plain(content, tone=tone)

    # Get client name for subject
    client_name = "tu proyecto"
    if digest.client_id:
        client_result = await db.execute(select(Client).where(Client.id == digest.client_id))
        client = client_result.scalar_one_or_none()
        if client:
            client_name = client.name

    subject = f"Resumen semanal — {client_name}"
    if body.test:
        subject = f"[TEST] {subject}"

    # Send email with both HTML and plain text (clients choose)
    from backend.services.email_service import send_email
    success = await send_email(
        to=body.to,
        subject=subject,
        body_html=html_body,
        body_text=plain_body,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Error al enviar email. Verifica la configuración SMTP.")

    # Update status to sent (skip if test mode)
    if not body.test:
        digest.status = DigestStatus.sent
        await db.commit()

    log_audit(current_user.id, "send_email", "digest", digest_id, details=f"to={body.to} test={body.test}")
    label = "Email de prueba enviado" if body.test else "Digest enviado"
    return {"success": True, "message": f"{label} a {body.to}"}


# ---------------------------------------------------------------------------
# DELETE /{id} — Delete a digest
# ---------------------------------------------------------------------------

@router.delete("/{digest_id}", status_code=204)
async def delete_digest(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Delete a digest. Admins can delete any; users can only delete their drafts."""
    result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
    digest = result.scalar_one_or_none()

    if not digest:
        raise HTTPException(status_code=404, detail="Digest no encontrado")

    is_admin = current_user.role == UserRole.admin
    is_owner = digest.created_by == current_user.id

    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este digest")

    if not is_admin and digest.status == DigestStatus.sent:
        raise HTTPException(status_code=409, detail="No puedes eliminar digests ya enviados")

    await db.delete(digest)
    await db.commit()
    log_audit(current_user.id, "delete", "digest", digest_id)
