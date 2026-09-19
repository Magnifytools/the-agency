"""Operational report-policy views; no provider calls or commits."""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    Delivery,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    User,
    WeeklyDigest,
)
from backend.schemas.digest import (
    DigestStateSummary,
    ExternalDeliverySummary,
    GenerationPreviewItem,
    InternalDistributionSummary,
    ReportPolicyResponse,
)
from backend.services.digest_access import user_has_digest_permission
from backend.services.digest_periods import policy_digest_period


async def policy_response(db, client_id: int, policy: ClientReportPolicy | None = None) -> ReportPolicyResponse:
    if policy is None:
        policy = await db.get(ClientReportPolicy, client_id)
    if policy is None:
        return ReportPolicyResponse(client_id=client_id, configured=False)
    responsible = None
    can_prepare = None
    if policy.responsible_user_id is not None:
        responsible = (await db.execute(
            select(User.full_name, User.is_active).where(User.id == policy.responsible_user_id)
        )).one_or_none()
        can_prepare = bool(responsible and await user_has_digest_permission(db, policy.responsible_user_id, write=True))
    return ReportPolicyResponse(
        client_id=client_id,
        configured=True,
        enabled=policy.enabled,
        cadence=policy.cadence,
        responsible_user_id=policy.responsible_user_id,
        responsible_name=responsible.full_name if responsible else None,
        responsible_active=responsible.is_active if responsible else None,
        responsible_can_prepare=can_prepare,
        revision=policy.revision,
        updated_at=policy.updated_at,
    )


async def external_delivery_state(db, digest: WeeklyDigest) -> tuple[ExternalDeliverySummary, bool]:
    latest = (await db.execute(
        select(DigestExternalDeliveryEvent, User.full_name)
        .join(User, User.id == DigestExternalDeliveryEvent.actor_id)
        .where(DigestExternalDeliveryEvent.digest_id == digest.id)
        .order_by(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc())
        .limit(1)
    )).one_or_none()
    active = bool(latest and latest[0].action == ExternalDeliveryAction.confirmed)
    summary = ExternalDeliverySummary(
        digest_id=digest.id,
        state="confirmed" if active else "unconfirmed",
        actor_name=latest[1] if active else None,
        confirmed_at=latest[0].created_at if active else None,
    )
    has_newer = bool(await db.scalar(select(
        select(WeeklyDigest.id).where(
            WeeklyDigest.client_id == digest.client_id,
            WeeklyDigest.period_start == digest.period_start,
            WeeklyDigest.period_end == digest.period_end,
            or_(
                WeeklyDigest.created_at > digest.created_at,
                and_(WeeklyDigest.created_at == digest.created_at, WeeklyDigest.id > digest.id),
            ),
        ).exists()
    )))
    return summary, has_newer


async def _active_period_delivery(db, client_id, period_start, period_end) -> ExternalDeliverySummary:
    ranked = select(
        DigestExternalDeliveryEvent.digest_id.label("digest_id"),
        DigestExternalDeliveryEvent.action.label("action"),
        DigestExternalDeliveryEvent.actor_id.label("actor_id"),
        DigestExternalDeliveryEvent.created_at.label("event_created_at"),
        func.row_number().over(
            partition_by=DigestExternalDeliveryEvent.digest_id,
            order_by=(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc()),
        ).label("event_rank"),
    ).subquery()
    row = (await db.execute(
        select(ranked.c.digest_id, User.full_name, ranked.c.event_created_at)
        .join(WeeklyDigest, WeeklyDigest.id == ranked.c.digest_id)
        .join(User, User.id == ranked.c.actor_id)
        .where(
            ranked.c.event_rank == 1,
            ranked.c.action == ExternalDeliveryAction.confirmed,
            WeeklyDigest.client_id == client_id,
            WeeklyDigest.period_start == period_start,
            WeeklyDigest.period_end == period_end,
        )
        .order_by(WeeklyDigest.created_at.desc(), WeeklyDigest.id.desc())
        .limit(1)
    )).one_or_none()
    if not row:
        return ExternalDeliverySummary()
    return ExternalDeliverySummary(
        digest_id=row.digest_id,
        state="confirmed",
        actor_name=row.full_name,
        confirmed_at=row.event_created_at,
    )


async def preview_item(db, client: Client, policy: ClientReportPolicy | None) -> GenerationPreviewItem:
    period_start = period_end = None
    responsible = None
    responsible_ok = False
    if policy:
        period_start, period_end = policy_digest_period(policy.cadence.value)
        if policy.responsible_user_id:
            responsible = (await db.execute(
                select(User.full_name, User.is_active).where(User.id == policy.responsible_user_id)
            )).one_or_none()
            responsible_ok = bool(responsible and await user_has_digest_permission(db, policy.responsible_user_id, write=True))

    latest = None
    version_count = 0
    if period_start and period_end:
        version_count = int(await db.scalar(select(func.count(WeeklyDigest.id)).where(
            WeeklyDigest.client_id == client.id,
            WeeklyDigest.period_start == period_start,
            WeeklyDigest.period_end == period_end,
        )) or 0)
        latest = (await db.execute(
            select(WeeklyDigest.id, WeeklyDigest.status, WeeklyDigest.created_at).where(
                WeeklyDigest.client_id == client.id,
                WeeklyDigest.period_start == period_start,
                WeeklyDigest.period_end == period_end,
            ).order_by(WeeklyDigest.created_at.desc(), WeeklyDigest.id.desc()).limit(1)
        )).one_or_none()

    internal = InternalDistributionSummary()
    external = ExternalDeliverySummary()
    if latest:
        delivery = (await db.execute(
            select(Delivery.id, Delivery.status, Delivery.sent_at).where(
                Delivery.source_kind == "digest", Delivery.source_id == latest.id
            ).order_by(Delivery.created_at.desc(), Delivery.id.desc()).limit(1)
        )).one_or_none()
        if delivery:
            internal = InternalDistributionSummary(
                digest_id=latest.id, state=delivery.status, delivery_id=delivery.id, sent_at=delivery.sent_at
            )
        external = await _active_period_delivery(db, client.id, period_start, period_end)

    if client.status != ClientStatus.active:
        reason = "client_inactive"
    elif client.is_internal:
        reason = "internal_client"
    elif policy is None:
        reason = "policy_missing"
    elif not policy.enabled:
        reason = "policy_disabled"
    elif not responsible_ok:
        reason = "responsible_unavailable"
    elif latest:
        reason = "already_exists"
    else:
        reason = "eligible"

    if policy is None:
        state = "not_configured"
    elif not policy.enabled:
        state = "disabled"
    elif not responsible_ok:
        state = "blocked_responsible"
    elif latest is None:
        state = "missing"
    elif external.state == "confirmed" and external.digest_id != latest.id:
        state = "newer_version_unconfirmed"
    elif external.state == "confirmed":
        state = "externally_delivered"
    elif internal.state == "sent":
        state = "internal_shared"
    else:
        state = latest.status.value

    return GenerationPreviewItem(
        client_id=client.id,
        client_name=client.name,
        policy_revision=policy.revision if policy else None,
        cadence=policy.cadence if policy else None,
        responsible_user_id=policy.responsible_user_id if policy else None,
        responsible_name=responsible.full_name if responsible else None,
        period_start=period_start,
        period_end=period_end,
        eligible=reason == "eligible",
        reason=reason,
        latest_digest_id=latest.id if latest else None,
        version_count=version_count,
        state=state,
        digest=DigestStateSummary(
            latest_digest_id=latest.id if latest else None,
            latest_status=latest.status if latest else None,
            version_count=version_count,
        ),
        internal_distribution=internal,
        external_delivery=external,
    )
