"""Opt-in client report policies and generation cohort preview."""
from __future__ import annotations

from typing import Literal

import hashlib
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.api.deps import require_admin, require_module
from backend.db.database import get_db
from backend.db.models import (
    Client,
    ClientReportPolicy,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    User,
    UserPermission,
    UserRole,
    WeeklyDigest,
)
from backend.schemas.digest import (
    CohortGenerateRequest,
    CohortGenerateResponse,
    CohortGenerateResult,
    GenerationPreviewResponse,
    ExternalDeliveryEventCreate,
    ExternalDeliveryEventResponse,
    ExternalDeliveryEventsResponse,
    ExternalDeliveryMutationResponse,
    PolicyResponsibleResponse,
    ReportPolicyResponse,
    ReportPolicyUpdate,
)
from backend.core.rate_limiter import ai_limiter
from backend.services.digest_access import authorize_digest, user_has_digest_permission, validate_responsible
from backend.services.digest_generation import DigestGenerationRejected, generate_locked_digest
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_generator import generate_digest_content
from backend.services.report_policy import external_delivery_state, policy_response, preview_item
from backend.services.temporal import business_today

router = APIRouter(prefix="/api/digests", tags=["digest-report-policy"])
logger = logging.getLogger(__name__)


@router.get("/policy-responsibles", response_model=list[PolicyResponsibleResponse])
async def list_policy_responsibles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    users = list((await db.execute(
        select(User.id, User.full_name).where(User.is_active.is_(True)).order_by(User.full_name, User.id)
    )).all())
    result = []
    for user in users:
        if await user_has_digest_permission(db, user.id, write=True):
            result.append(PolicyResponsibleResponse(id=user.id, full_name=user.full_name))
    return result


@router.get("/policies/{client_id}", response_model=ReportPolicyResponse)
async def get_report_policy(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    client_exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if client_exists is None:
        raise HTTPException(404, "Client not found")
    policy = await db.get(ClientReportPolicy, client_id)
    if current_user.role != UserRole.admin and (
        policy is None or policy.responsible_user_id != current_user.id
    ):
        raise HTTPException(403, "No tienes acceso a esta política")
    return await policy_response(db, client_id, policy)


@router.put("/policies/{client_id}", response_model=ReportPolicyResponse)
async def put_report_policy(
    client_id: int,
    request: ReportPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    client_exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if client_exists is None:
        raise HTTPException(404, "Client not found")
    if request.enabled and request.responsible_user_id is None:
        raise HTTPException(422, detail={"code": "responsible_required", "message": "Selecciona una persona responsable"})
    await validate_responsible(db, request.responsible_user_id)

    policy = (await db.execute(
        select(ClientReportPolicy).where(ClientReportPolicy.client_id == client_id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if policy is None:
        if request.revision != 0:
            raise HTTPException(409, detail={"code": "policy_changed", "current": (await policy_response(db, client_id)).model_dump(mode="json")})
        policy = ClientReportPolicy(
            client_id=client_id,
            enabled=request.enabled,
            cadence=request.cadence,
            responsible_user_id=request.responsible_user_id,
            revision=1,
        )
        db.add(policy)
    else:
        if request.revision != policy.revision:
            raise HTTPException(409, detail={"code": "policy_changed", "current": (await policy_response(db, client_id, policy)).model_dump(mode="json")})
        policy.enabled = request.enabled
        policy.cadence = request.cadence
        policy.responsible_user_id = request.responsible_user_id
        policy.revision += 1
    await db.commit()
    await db.refresh(policy)
    return await policy_response(db, client_id, policy)


@router.get("/generation-preview", response_model=GenerationPreviewResponse)
async def generation_preview(
    scope: Literal["mine", "team"] = Query("mine"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    if scope == "team" and current_user.role != UserRole.admin:
        raise HTTPException(403, "El ámbito Equipo requiere permisos de administrador")

    if scope == "mine":
        rows = (await db.execute(
            select(Client, ClientReportPolicy)
            .join(ClientReportPolicy, ClientReportPolicy.client_id == Client.id)
            .where(ClientReportPolicy.responsible_user_id == current_user.id)
            .options(noload(Client.projects), noload(Client.tasks))
            .order_by(Client.name, Client.id)
        )).all()
    else:
        rows = (await db.execute(
            select(Client, ClientReportPolicy)
            .outerjoin(ClientReportPolicy, ClientReportPolicy.client_id == Client.id)
            .options(noload(Client.projects), noload(Client.tasks))
            .order_by(Client.name, Client.id)
        )).all()

    items = [await preview_item(db, client, policy) for client, policy in rows]
    return GenerationPreviewResponse(
        as_of=business_today(),
        scope=scope,
        items=items,
        counts={"eligible": sum(item.eligible for item in items), "excluded": sum(not item.eligible for item in items)},
    )


@router.post("/generate-cohort", response_model=CohortGenerateResponse)
async def generate_cohort(
    request: CohortGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    ai_limiter.check(current_user.id, max_requests=3, window_seconds=60)
    actor_id = current_user.id
    await db.rollback()  # each item below owns an independent transaction
    results: list[CohortGenerateResult] = []
    for item in sorted(request.items, key=lambda value: (value.client_id, value.period_start, value.period_end)):
        try:
            digest = await generate_locked_digest(
                db,
                actor_id=actor_id,
                client_id=item.client_id,
                period_start=item.period_start,
                period_end=item.period_end,
                tone=request.tone,
                expected_revision=item.policy_revision,
                require_enabled=True,
                reject_existing=True,
                collector=collect_digest_data,
                generator=generate_digest_content,
            )
            digest_id = digest.id
            await db.commit()
            results.append(CohortGenerateResult(client_id=item.client_id, outcome="generated", digest_id=digest_id))
        except DigestGenerationRejected as exc:
            await db.rollback()
            results.append(CohortGenerateResult(client_id=item.client_id, outcome="skipped", reason=exc.reason))
        except Exception:
            await db.rollback()
            logger.exception("Cohort digest generation failed for client_id=%s", item.client_id)
            results.append(CohortGenerateResult(client_id=item.client_id, outcome="failed", reason="generation_failed"))
    return CohortGenerateResponse(results=results)


async def _external_events_response(db, digest: WeeklyDigest, actor: User) -> ExternalDeliveryEventsResponse:
    rows = (await db.execute(
        select(DigestExternalDeliveryEvent, User.full_name)
        .join(User, User.id == DigestExternalDeliveryEvent.actor_id)
        .where(DigestExternalDeliveryEvent.digest_id == digest.id)
        .order_by(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc())
    )).all()
    external, has_newer = await external_delivery_state(db, digest)
    try:
        await authorize_digest(db, digest.id, actor, write=True)
        can_record = True
    except HTTPException:
        can_record = False
    return ExternalDeliveryEventsResponse(
        events=[ExternalDeliveryEventResponse(
            id=event.id,
            digest_id=event.digest_id,
            action=event.action,
            actor_id=event.actor_id,
            actor_name=actor_name,
            created_at=event.created_at,
        ) for event, actor_name in rows],
        external_delivery=external,
        has_newer_version=has_newer,
        can_record=can_record,
    )


@router.get("/{digest_id}/external-delivery-events", response_model=ExternalDeliveryEventsResponse)
async def list_external_delivery_events(
    digest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests")),
):
    digest = await authorize_digest(db, digest_id, current_user, write=False)
    return await _external_events_response(db, digest, current_user)


@router.post("/{digest_id}/external-delivery-events", response_model=ExternalDeliveryMutationResponse)
async def record_external_delivery_event(
    digest_id: int,
    request: ExternalDeliveryEventCreate,
    request_key: str = Header(alias="X-Agency-Request-Key", min_length=16, max_length=80),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("digests", write=True)),
):
    digest = await authorize_digest(db, digest_id, current_user, write=True, lock=True)
    request_hash = hashlib.sha256(f"{digest_id}:{request.action.value}".encode()).hexdigest()
    existing = (await db.execute(select(DigestExternalDeliveryEvent).where(
        DigestExternalDeliveryEvent.actor_id == current_user.id,
        DigestExternalDeliveryEvent.request_key == request_key,
    ))).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, detail={"code": "idempotency_conflict"})
        response = await _external_events_response(db, digest, current_user)
        event = next(value for value in response.events if value.id == existing.id)
        return ExternalDeliveryMutationResponse(
            event=event,
            external_delivery=response.external_delivery,
            has_newer_version=response.has_newer_version,
            can_record=response.can_record,
        )

    latest = (await db.execute(
        select(DigestExternalDeliveryEvent).where(DigestExternalDeliveryEvent.digest_id == digest_id)
        .order_by(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    active = bool(latest and latest.action == ExternalDeliveryAction.confirmed)
    if request.action == ExternalDeliveryAction.confirmed and active:
        raise HTTPException(409, detail={"code": "already_confirmed"})
    if request.action == ExternalDeliveryAction.revoked and not active:
        raise HTTPException(409, detail={"code": "not_confirmed"})

    event = DigestExternalDeliveryEvent(
        digest_id=digest_id,
        action=request.action,
        actor_id=current_user.id,
        request_key=request_key,
        request_hash=request_hash,
    )
    db.add(event)
    await db.flush()
    event_id = event.id
    await db.commit()
    digest = await authorize_digest(db, digest_id, current_user, write=False)
    response = await _external_events_response(db, digest, current_user)
    created = next(value for value in response.events if value.id == event_id)
    return ExternalDeliveryMutationResponse(
        event=created,
        external_delivery=response.external_delivery,
        has_newer_version=response.has_newer_version,
        can_record=response.can_record,
    )
