"""Operational report-policy views; no provider calls or commits."""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from backend.db.models import (
    Client,
    ClientLocalReport,
    ClientLocalReportConfig,
    ClientReportPolicy,
    ClientStatus,
    Delivery,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.schemas.digest import (
    DigestStateSummary,
    ExternalDeliverySummary,
    GenerationPreviewItem,
    InternalDistributionSummary,
    LocalReportSummary,
    ReportPolicyResponse,
)
from backend.services.digest_access import permission_exists, user_has_digest_permission
from backend.services.digest_periods import enabled_cadences, policy_digest_period


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
        enabled=policy.weekly_enabled or policy.monthly_enabled,
        weekly_enabled=policy.weekly_enabled,
        monthly_enabled=policy.monthly_enabled,
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


async def preview_items(db, rows) -> list[GenerationPreviewItem]:
    """Project the cohort in four bounded queries, without loading digest content.

    One item per enabled cadence (monthly first); a client without policy or
    with both cadences off still gets one excluded item. Rank only reports in
    the requested coverage and receipts for those reports, per (client,
    period). Query count does not grow with clients or their historical versions.
    """
    if not rows:
        return []
    entries = [
        (client, policy, cadence)
        for client, policy in rows
        for cadence in (enabled_cadences(policy) or [None])
    ]
    periods = {
        cadence: policy_digest_period(cadence)
        for _, _, cadence in entries if cadence is not None
    }
    responsible_ids = {policy.responsible_user_id for _, policy in rows if policy and policy.responsible_user_id}
    responsible_by_id = {}
    if responsible_ids:
        responsible_by_id = {row.id: row for row in (await db.execute(
            select(
                User.id, User.full_name,
                and_(User.is_active.is_(True), or_(
                    User.role == UserRole.admin,
                    permission_exists(User.id, write=True),
                )).label("can_prepare"),
            ).where(User.id.in_(responsible_ids))
        )).all()}

    latest_by_period = {}
    internal_by_digest = {}
    external_by_period = {}
    if periods:
        coverage = or_(*[
            and_(
                WeeklyDigest.client_id.in_([client.id for client, _, value in entries if value == cadence]),
                WeeklyDigest.period_start == period_start,
                WeeklyDigest.period_end == period_end,
            ) for cadence, (period_start, period_end) in periods.items()
        ])
        coverage_key = (WeeklyDigest.client_id, WeeklyDigest.period_start, WeeklyDigest.period_end)
        ranked_digests = select(
            WeeklyDigest.id, WeeklyDigest.client_id, WeeklyDigest.period_start, WeeklyDigest.period_end,
            WeeklyDigest.status,
            func.count().over(partition_by=coverage_key).label("version_count"),
            func.row_number().over(
                partition_by=coverage_key,
                order_by=(WeeklyDigest.created_at.desc(), WeeklyDigest.id.desc()),
            ).label("version_rank"),
        ).where(coverage).subquery()
        latest_by_period = {(row.client_id, row.period_start, row.period_end): row for row in (await db.execute(
            select(ranked_digests).where(ranked_digests.c.version_rank == 1)
        )).all()}

        if latest_by_period:
            ranked_deliveries = select(
                Delivery.id, Delivery.source_id, Delivery.status, Delivery.sent_at,
                func.row_number().over(
                    partition_by=Delivery.source_id,
                    order_by=(Delivery.created_at.desc(), Delivery.id.desc()),
                ).label("delivery_rank"),
            ).where(
                Delivery.source_kind == "digest",
                Delivery.source_id.in_([row.id for row in latest_by_period.values()]),
            ).subquery()
            internal_by_digest = {row.source_id: InternalDistributionSummary(
                digest_id=row.source_id, state=row.status, delivery_id=row.id, sent_at=row.sent_at,
            ) for row in (await db.execute(
                select(ranked_deliveries).where(ranked_deliveries.c.delivery_rank == 1)
            )).all()}

            # Determine latest event per version before choosing a confirmed
            # version. A revoked version must never inherit an earlier event.
            ranked_events = select(
                DigestExternalDeliveryEvent.digest_id,
                DigestExternalDeliveryEvent.action,
                DigestExternalDeliveryEvent.actor_id,
                DigestExternalDeliveryEvent.created_at.label("event_created_at"),
                WeeklyDigest.client_id,
                WeeklyDigest.period_start,
                WeeklyDigest.period_end,
                WeeklyDigest.created_at.label("digest_created_at"),
                func.row_number().over(
                    partition_by=DigestExternalDeliveryEvent.digest_id,
                    order_by=(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc()),
                ).label("event_rank"),
            ).join(WeeklyDigest, WeeklyDigest.id == DigestExternalDeliveryEvent.digest_id).where(coverage).subquery()
            confirmed_versions = select(
                ranked_events,
                func.row_number().over(
                    partition_by=(ranked_events.c.client_id, ranked_events.c.period_start, ranked_events.c.period_end),
                    order_by=(ranked_events.c.digest_created_at.desc(), ranked_events.c.digest_id.desc()),
                ).label("confirmed_rank"),
            ).where(
                ranked_events.c.event_rank == 1,
                ranked_events.c.action == ExternalDeliveryAction.confirmed,
            ).subquery()
            external_by_period = {(row.client_id, row.period_start, row.period_end): ExternalDeliverySummary(
                digest_id=row.digest_id, state="confirmed", actor_name=row.full_name,
                confirmed_at=row.event_created_at,
            ) for row in (await db.execute(
                select(confirmed_versions.c.client_id, confirmed_versions.c.period_start,
                       confirmed_versions.c.period_end, confirmed_versions.c.digest_id,
                       confirmed_versions.c.event_created_at, User.full_name)
                .join(User, User.id == confirmed_versions.c.actor_id)
                .where(confirmed_versions.c.confirmed_rank == 1)
            )).all()}

    local_by_client = await _local_reports(
        db, [client.id for client, _, cadence in entries if cadence == "monthly"], periods.get("monthly"),
    )
    items = []
    for client, policy, cadence in entries:
        period = periods.get(cadence) if cadence else None
        key = (client.id, *period) if period else None
        items.append(_preview_item(
            client, policy, cadence, period,
            responsible_by_id.get(policy.responsible_user_id) if policy else None,
            latest_by_period.get(key), internal_by_digest, external_by_period.get(key),
            local_by_client.get(client.id) if cadence == "monthly" else None,
        ))
    return items


async def _local_reports(db, client_ids: list[int], month) -> dict[int, LocalReportSummary]:
    """Clientes con informe SEO local: su versión del mes (la entregada, si hay; si no,
    la última). Es del mes en que empieza, como en ``report_unsent``."""
    if not client_ids or month is None:
        return {}
    month_start, month_end = month
    ranked = select(
        ClientLocalReport.client_id, ClientLocalReport.id, ClientLocalReport.delivered_at,
        ClientLocalReport.delivered_by,
        func.row_number().over(
            partition_by=ClientLocalReport.client_id,
            order_by=(ClientLocalReport.delivered_at.is_(None), ClientLocalReport.id.desc()),
        ).label("rank"),
    ).where(
        ClientLocalReport.client_id.in_(client_ids),
        ClientLocalReport.period_start.between(month_start, month_end),
    ).subquery()
    rows = (await db.execute(
        select(ClientLocalReportConfig.client_id, ranked.c.id, ranked.c.delivered_at, User.full_name)
        .outerjoin(ranked, and_(ranked.c.client_id == ClientLocalReportConfig.client_id, ranked.c.rank == 1))
        .outerjoin(User, User.id == ranked.c.delivered_by)
        .where(ClientLocalReportConfig.client_id.in_(client_ids))
    )).all()
    return {row.client_id: LocalReportSummary(
        report_id=row.id, delivered_at=row.delivered_at,
        delivered_by_name=row.full_name if row.delivered_at else None,
    ) for row in rows}


def _preview_item(client, policy, cadence, period, responsible, latest, internal_by_digest, external, local=None):
    period_start, period_end = period or (None, None)
    responsible_ok = bool(responsible and responsible.can_prepare)
    internal = internal_by_digest.get(latest.id, InternalDistributionSummary()) if latest else InternalDistributionSummary()
    external = external or ExternalDeliverySummary()

    if client.status != ClientStatus.active:
        reason = "client_inactive"
    elif client.is_internal:
        reason = "internal_client"
    elif policy is None:
        reason = "policy_missing"
    elif cadence is None:
        reason = "policy_disabled"
    elif not responsible_ok:
        reason = "responsible_unavailable"
    elif local is not None:
        # El mes lo cubre el informe SEO local (su pestaña), no un resumen.
        reason = "local_report"
    elif latest:
        reason = "already_exists"
    else:
        reason = "eligible"

    if policy is None:
        state = "not_configured"
    elif cadence is None:
        state = "disabled"
    elif not responsible_ok:
        state = "blocked_responsible"
    elif local is not None:
        state = ("local_delivered" if local.delivered_at else
                 "local_prepared" if local.report_id else "local_missing")
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
        cadence=cadence,
        responsible_user_id=policy.responsible_user_id if policy else None,
        responsible_name=responsible.full_name if responsible else None,
        period_start=period_start,
        period_end=period_end,
        eligible=reason == "eligible",
        reason=reason,
        latest_digest_id=latest.id if latest else None,
        version_count=latest.version_count if latest else 0,
        state=state,
        digest=DigestStateSummary(
            latest_digest_id=latest.id if latest else None,
            latest_status=latest.status if latest else None,
            version_count=latest.version_count if latest else 0,
        ),
        internal_distribution=internal,
        external_delivery=external,
        local_report=local,
    )
