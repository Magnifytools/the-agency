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

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.deps import require_module
from backend.api.middleware.audit_log import log_audit
from backend.api.utils.db_helpers import safe_refresh
from backend.core.rate_limiter import ai_limiter
from backend.db.database import get_db
from backend.db.models import (
    Delivery,
    DigestExternalDeliveryEvent,
    DigestStatus,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.schemas.digest import (
    DigestContent,
    DigestGenerateRequest,
    DigestRenderResponse,
    DigestResponse,
    DigestStatusUpdate,
    DigestUpdateRequest,
)
from backend.services.digest_access import authorize_digest, digest_visibility_clause
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_generation import (
    DigestGenerationRejected,
    find_generation,
    generate_locked_digest,
    regenerate_digest,
)
from backend.services.digest_generator import (
    DigestProviderError,
    generate_digest_content,
)
from backend.services.digest_periods import (
    canonicalize_digest_content,
    resolve_digest_period,
)
from backend.services.digest_renderer import (
    render_discord,
    render_email,
    render_email_plain,
    render_slack,
)

router = APIRouter(prefix="/api/digests", tags=["digests"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_period_or_422(
    period_start: date | None, period_end: date | None
) -> tuple[date, date]:
    try:
        return resolve_digest_period(period_start, period_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _human_content(
    content: dict, previous: dict | None, raw_context: dict | None
) -> dict:
    """Only unchanged assertions may retain validated generated provenance."""
    previous_sections = (previous or {}).get("sections", {})
    catalog = (raw_context or {}).get("source_catalog", {})
    for section, items in content.get("sections", {}).items():
        old_items = previous_sections.get(section, [])
        for index, item in enumerate(items):
            old = old_items[index] if index < len(old_items) else None
            unchanged = bool(
                old
                and all(
                    item.get(field, "") == old.get(field, "")
                    for field in ("title", "description")
                )
            )
            keys = item.get("source_keys", []) if unchanged else []
            item["source_keys"] = [key for key in keys if key in catalog][:8]
    return content


def _public_context(raw_context: dict | None) -> dict | None:
    if raw_context is None:
        return None
    return {key: value for key, value in raw_context.items() if key != "_generation"}


def _generation_rejection(reason: str) -> HTTPException:
    messages = {
        "generation_key_conflict": "Esta clave de recuperación pertenece a otra intención. Recarga antes de intentarlo de nuevo.",
        "permission_changed": "Ya no tienes permiso para preparar este resumen.",
        "already_exists": "Ya existe un resumen para esta cohorte y período.",
        "source_catalog_missing": "No se pudieron identificar las fuentes del resumen.",
    }
    status = 403 if reason == "permission_changed" else 409
    return HTTPException(
        status,
        detail={
            "code": reason,
            "message": messages.get(
                reason,
                "El contexto del resumen ha cambiado. Recarga antes de reintentar.",
            ),
        },
    )


def _to_response(digest: WeeklyDigest) -> DigestResponse:
    """Convert ORM model to response schema."""
    content = None
    if digest.content:
        try:
            parsed = DigestContent(**digest.content)
            content = DigestContent(
                **canonicalize_digest_content(
                    parsed.model_dump(), digest.period_start, digest.period_end
                )
            )
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
        raw_context=_public_context(digest.raw_context),
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

    period_start, period_end = _resolve_period_or_422(
        request.period_start, request.period_end
    )

    try:
        digest = await generate_locked_digest(
            db,
            actor_id=current_user.id,
            client_id=request.client_id,
            period_start=period_start,
            period_end=period_end,
            tone=request.tone,
            generation_key=request.generation_key,
            expected_revision=None,
            require_enabled=False,
            reject_existing=False,
            collector=collect_digest_data,
            generator=generate_digest_content,
        )
    except DigestGenerationRejected as exc:
        await db.rollback()
        raise _generation_rejection(exc.reason) from exc
    except DigestProviderError as exc:
        await db.rollback()
        status = 504 if exc.code == "provider_timeout" else 503
        raise HTTPException(
            status_code=status,
            detail={
                "code": exc.code,
                "message": "El proveedor no respondió a tiempo. Puedes reintentar de forma segura con la misma clave."
                if status == 504
                else "El proveedor de generación no está disponible.",
            },
        ) from exc
    except ValueError:
        await db.rollback()
        raise HTTPException(
            status_code=502,
            detail={
                "code": "invalid_provider_response",
                "message": "El proveedor devolvió un resumen no válido.",
            },
        )
    except Exception as exc:
        await db.rollback()
        logger.error(
            "Digest generation failed for client_id=%s type=%s",
            request.client_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_failed",
                "message": "No se pudo generar el resumen.",
            },
        )
    await db.commit()
    await safe_refresh(db, digest, log_context="digests")

    log_audit(
        current_user.id,
        "generate",
        "digest",
        digest.id,
        details=f"client_id={request.client_id}",
    )
    # Reload with relationships for response
    result = await db.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.id == digest.id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
    return _to_response(result.scalar_one())


# ---------------------------------------------------------------------------
# POST /generate-batch — Generate digests for all active clients
# ---------------------------------------------------------------------------


@router.post("/generate-batch")
async def generate_batch_retired(
    current_user: User = Depends(require_module("digests", write=True)),
):
    """Retired with the policy cohort UI; never bypass preview/revalidation."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "legacy_batch_retired",
            "message": "Usa la vista previa de cohorte",
        },
    )


# ---------------------------------------------------------------------------
# GET / — List digests
# ---------------------------------------------------------------------------


@router.get("", response_model=list[DigestResponse])
async def list_digests(
    client_id: Optional[int] = Query(None),
    status: Optional[DigestStatus] = Query(None),
    period_from: Optional[date] = Query(None, description="YYYY-MM-DD"),
    period_to: Optional[date] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    """List digests with optional filters."""
    if period_from and period_to and period_to < period_from:
        raise HTTPException(422, "period_to no puede ser anterior a period_from")
    query = select(WeeklyDigest)

    if client_id:
        query = query.where(WeeklyDigest.client_id == client_id)
    if status:
        query = query.where(WeeklyDigest.status == status)
    if period_from:
        query = query.where(WeeklyDigest.period_start >= period_from)
    if period_to:
        query = query.where(WeeklyDigest.period_end <= period_to)
    visibility = digest_visibility_clause(current_user)
    if visibility is not None:
        query = query.where(visibility)

    query = query.options(
        selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator)
    )
    query = (
        query.order_by(WeeklyDigest.created_at.desc(), WeeklyDigest.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)

    return [_to_response(d) for d in result.scalars().all()]


@router.get("/generation/{generation_key}", response_model=DigestResponse)
async def recover_generation(
    generation_key: str = Path(
        min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    digest = await find_generation(
        db, actor_id=current_user.id, generation_key=generation_key
    )
    if digest is None:
        raise HTTPException(
            404,
            detail={
                "code": "generation_not_confirmed",
                "message": "Todavía no hay un resultado confirmado. Comprueba de nuevo o reintenta con la misma clave.",
            },
        )
    digest = await authorize_digest(db, digest.id, current_user, write=False)
    return _to_response(digest)


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
    digest = await authorize_digest(db, digest_id, current_user, write=False)

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
    """Create a new digest version when content or tone changes.

    If only the tone changes (no content update), auto-regenerate
    content using stored raw_context. Identical payloads return the same ID.
    """
    digest = await authorize_digest(db, digest_id, current_user, write=True)

    next_tone = request.tone if request.tone is not None else digest.tone
    tone_changed = next_tone != digest.tone
    next_content = (
        _human_content(
            canonicalize_digest_content(
                request.content.model_dump(), digest.period_start, digest.period_end
            ),
            digest.content,
            digest.raw_context,
        )
        if request.content is not None
        else digest.content
    )
    try:
        current_content = canonicalize_digest_content(
            DigestContent(**(digest.content or {})).model_dump(),
            digest.period_start,
            digest.period_end,
        )
    except Exception:
        current_content = digest.content
    content_changed = request.content is not None and next_content != current_content

    if not tone_changed and not content_changed:
        return _to_response(digest)

    # If tone changed without an explicit content update, regenerate content
    if tone_changed and request.content is None:
        if not request.generation_key:
            raise HTTPException(
                422,
                detail={
                    "code": "generation_key_required",
                    "message": "Recarga el resumen y reintenta el cambio de tono para conservar una clave de recuperación.",
                },
            )
        if not digest.raw_context:
            raise HTTPException(
                status_code=400,
                detail="No hay datos crudos para regenerar el digest con el nuevo tono",
            )
        ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)
        try:
            version = await regenerate_digest(
                db,
                actor_id=current_user.id,
                source=digest,
                tone=next_tone,
                generation_key=request.generation_key,
                generator=generate_digest_content,
            )
        except DigestProviderError as exc:
            await db.rollback()
            status = 504 if exc.code == "provider_timeout" else 503
            raise HTTPException(
                status,
                detail={
                    "code": exc.code,
                    "message": "El proveedor no respondió a tiempo. Reintenta con la misma clave."
                    if status == 504
                    else "El proveedor no está disponible.",
                },
            ) from exc
        except DigestGenerationRejected as exc:
            await db.rollback()
            raise _generation_rejection(exc.reason) from exc
        except ValueError:
            await db.rollback()
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "invalid_provider_response",
                    "message": "El proveedor devolvió un resumen no válido.",
                },
            )
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Digest regeneration failed id=%s type=%s",
                digest_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "provider_failed",
                    "message": "No se pudo regenerar el resumen.",
                },
            )
        await db.commit()
        await safe_refresh(db, version, log_context="digests")
        version_result = await db.execute(
            select(WeeklyDigest)
            .where(WeeklyDigest.id == version.id)
            .options(
                selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator)
            )
        )
        return _to_response(version_result.scalar_one())
    else:
        generated_at = digest.generated_at
        edited_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # An edit/regeneration is a new durable source version. The original ID and
    # any Delivery receipts remain tied to the exact content they represented.
    version = WeeklyDigest(
        client_id=digest.client_id,
        period_start=digest.period_start,
        period_end=digest.period_end,
        status=DigestStatus.draft,
        tone=next_tone,
        content=next_content,
        raw_context=_public_context(digest.raw_context),
        generated_at=generated_at,
        edited_at=edited_at,
        created_by=current_user.id,
    )
    db.add(version)
    await db.commit()
    await safe_refresh(db, version, log_context="digests")
    version_result = await db.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.id == version.id)
        .options(selectinload(WeeklyDigest.client), selectinload(WeeklyDigest.creator))
    )
    return _to_response(version_result.scalar_one())


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
    digest = await authorize_digest(db, digest_id, current_user, write=True)

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
    digest = await authorize_digest(db, digest_id, current_user, write=False)

    if not digest.content:
        raise HTTPException(status_code=400, detail="Digest has no content to render")

    try:
        content = DigestContent(**digest.content)
    except Exception:
        raise HTTPException(status_code=400, detail="Digest content is malformed")

    tone = digest.tone if digest.tone else None

    # Load client's Slack template if available
    client_template = None
    if digest.client and hasattr(digest.client, "slack_template"):
        client_template = digest.client.slack_template

    if format == "slack":
        rendered = render_slack(
            content,
            tone=tone,
            slack_template=client_template,
            period_start=digest.period_start,
            period_end=digest.period_end,
        )
    elif format == "discord":
        rendered = render_discord(
            content,
            tone=tone,
            period_start=digest.period_start,
            period_end=digest.period_end,
        )
    elif format == "email_plain":
        rendered = render_email_plain(
            content,
            tone=tone,
            period_start=digest.period_start,
            period_end=digest.period_end,
        )
    else:
        rendered = render_email(
            content,
            tone=tone,
            period_start=digest.period_start,
            period_end=digest.period_end,
        )

    return DigestRenderResponse(format=format, rendered=rendered)


# ---------------------------------------------------------------------------
# Live email sending removed by product policy: digests are delivered via
# generate → edit → render → copy-paste into Gmail/Slack manually.
# See the /{id}/render endpoint above. No app-initiated send.
# ---------------------------------------------------------------------------


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
    digest = await authorize_digest(db, digest_id, current_user, write=True, lock=True)

    is_admin = current_user.role == UserRole.admin

    if not is_admin and digest.status == DigestStatus.sent:
        raise HTTPException(
            status_code=409, detail="No puedes eliminar digests ya enviados"
        )

    has_evidence = await db.scalar(
        select(
            or_(
                exists().where(
                    Delivery.source_kind == "digest", Delivery.source_id == digest_id
                ),
                exists().where(DigestExternalDeliveryEvent.digest_id == digest_id),
            )
        )
    )
    if has_evidence:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "traceability_required",
                "message": "Este resumen tiene evidencia de distribución y no se puede eliminar",
            },
        )

    await db.delete(digest)
    await db.commit()
    log_audit(current_user.id, "delete", "digest", digest_id)
