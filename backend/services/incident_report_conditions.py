"""Bounded, read-only operational conditions for report policies and deliveries."""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, case, exists, false, func, or_, select
from sqlalchemy.orm import aliased

from backend.core.modules import is_enabled
from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    CommunicationOccurrence,
    CommunicationRequest,
    CommunicationSchedule,
    DailyUpdate,
    Delivery,
    DigestExternalDeliveryEvent,
    ExternalDeliveryAction,
    Notification,
    ReportCadence,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.services.digest_periods import format_month, policy_digest_period
from backend.services.incident_conditions import Condition, module_permission
from backend.services.manual_communications import KINDS as MANUAL_KINDS
from backend.services.scheduled_communications import KINDS as SCHEDULED_KINDS
from backend.services.temporal import business_today

REPORT_UNSENT = "report_unsent"
REPORT_CONDITIONS = ("report_pending", "delivery_failed", REPORT_UNSENT)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def _report_source_clause(user_id: int):
    """A policy is actionable only by its still-authorized explicit owner."""
    if not is_enabled("digests"):
        return false()
    return and_(
        ClientReportPolicy.enabled.is_(True),
        ClientReportPolicy.responsible_user_id == user_id,
        Client.status == ClientStatus.active,
        Client.is_internal.is_(False),
        module_permission(user_id, "digests", write=True),
    )


def _unsent_recipient_clause(user_id: int):
    """Admins, and the policy's responsible while they can still prepare digests."""
    if not is_enabled("digests"):
        return false()
    return or_(
        exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin),
        and_(
            ClientReportPolicy.responsible_user_id == user_id,
            module_permission(user_id, "digests", write=True),
        ),
    )


def _monthly_cycle_clause():
    """Active external clients whose enabled policy promises a monthly digest."""
    return and_(
        ClientReportPolicy.enabled.is_(True),
        ClientReportPolicy.cadence == ReportCadence.monthly,
        Client.status == ClientStatus.active,
        Client.is_internal.is_(False),
    )


def delivery_confirmed_clause(client_id, period_start, period_end):
    """Some version of the period has, as its latest event, a confirmed delivery.

    The external delivery event is the only proof that a digest reached the
    client; ``DigestStatus.sent`` is a legacy label nobody records evidence for.
    """
    latest_action = (
        select(DigestExternalDeliveryEvent.action)
        .where(DigestExternalDeliveryEvent.digest_id == WeeklyDigest.id)
        .order_by(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc())
        .limit(1)
        .correlate(WeeklyDigest)
        .scalar_subquery()
    )
    return exists().where(
        WeeklyDigest.client_id == client_id,
        WeeklyDigest.period_start == period_start,
        WeeklyDigest.period_end == period_end,
        latest_action == ExternalDeliveryAction.confirmed,
    )


def _unsent_key(client_id: int, period_start, period_end) -> str:
    return f"{REPORT_UNSENT}:client:{client_id}:monthly:{period_start.isoformat()}:{period_end.isoformat()}"


def _digest_source_clause(user_id: int):
    """The SQL equivalent of digest read access for a delivery's original actor."""
    if not is_enabled("digests"):
        return false()
    return and_(
        Delivery.actor_id == user_id,
        Delivery.source_kind == "digest",
        module_permission(user_id, "digests"),
        exists().where(
            WeeklyDigest.id == Delivery.source_id,
            or_(
                exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin),
                WeeklyDigest.created_by == user_id,
                exists().where(
                    ClientReportPolicy.client_id == WeeklyDigest.client_id,
                    ClientReportPolicy.responsible_user_id == user_id,
                ),
            ),
        ),
    )


def _delivery_source_clause(user_id: int):
    """Bounded SQL projection of ``authorize_source(..., write=False)``."""
    clauses = []
    if is_enabled("digests"):
        clauses.append(_digest_source_clause(user_id))
    if is_enabled("dailys"):
        admin = exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin)
        clauses.append(and_(
            Delivery.actor_id == user_id, Delivery.source_kind == "daily",
            exists().where(DailyUpdate.id == Delivery.source_id, or_(admin, DailyUpdate.user_id == user_id)),
        ))
    # Communications is a core delivery source even when its settings screen is
    # hidden; authorization follows the service, never the navigation flag.
    admin = exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin)
    manual = exists().where(
            CommunicationRequest.id == Delivery.source_id,
            CommunicationRequest.kind.in_(MANUAL_KINDS),
            CommunicationRequest.scope.in_(("mine", "team")),
            CommunicationRequest.destination_kind == case(
                (CommunicationRequest.kind == "weekly_report", "owner_dm"),
                else_="team_webhook",
            ),
            or_(
                admin,
                and_(CommunicationRequest.owner_id == user_id, CommunicationRequest.kind == "pm_briefing", CommunicationRequest.scope == "mine", module_permission(user_id, "pm")),
            ),
    )
    scheduled = exists().where(
            CommunicationRequest.id == Delivery.source_id,
            CommunicationOccurrence.request_id == CommunicationRequest.id,
            CommunicationSchedule.id == CommunicationOccurrence.schedule_id,
            CommunicationOccurrence.kind.in_(SCHEDULED_KINDS),
            CommunicationRequest.kind == ("scheduled_" + CommunicationOccurrence.kind),
            CommunicationRequest.destination_kind == CommunicationOccurrence.channel,
            CommunicationRequest.scope == case((CommunicationOccurrence.kind.in_(("weekly", "team_morning")), "team"), else_="mine"),
            CommunicationRequest.period_start == CommunicationOccurrence.period_start,
            CommunicationRequest.period_end == CommunicationOccurrence.period_end,
            CommunicationRequest.owner_id == CommunicationOccurrence.recipient_id,
            or_(
                admin,
                and_(
                    CommunicationRequest.owner_id == user_id,
                    CommunicationOccurrence.kind.not_in(("weekly", "team_morning")),
                    or_(
                        CommunicationOccurrence.kind == "meeting",
                        module_permission(user_id, "tasks"),
                    ),
                ),
            ),
    )
    clauses.append(and_(Delivery.actor_id == user_id, Delivery.source_kind == "communication", or_(manual, scheduled)))
    return or_(*clauses) if clauses else false()


def report_visibility_clause(user_id: int, *, current_only: bool = False, now: datetime | None = None):
    """Current permission/source predicate for report-related Notification rows.

    ``current_only`` keeps an incident live only while its report is still
    missing or a delivery has not been superseded by a reviewed resend.
    """
    report_live = exists().where(
        ClientReportPolicy.client_id == Notification.entity_id,
        Client.id == ClientReportPolicy.client_id,
        _report_source_clause(user_id),
    )
    replacement = aliased(Delivery)
    delivery_filters = [
        Delivery.id == Notification.entity_key,
        _delivery_source_clause(user_id),
    ]
    if current_only:
        delivery_filters.extend((
            Delivery.status.in_(("failed", "uncertain")),
            ~exists().where(replacement.resend_of == Delivery.id),
            Notification.dedupe_key == func.concat("delivery_failed:delivery:", Delivery.id, ":", Delivery.status),
        ))
    delivery_live = exists().where(*delivery_filters)
    if current_only:
        today = business_today(now=now)
        weekly_start, weekly_end = policy_digest_period("weekly", today=today)
        monthly_start, monthly_end = policy_digest_period("monthly", today=today)
        digest_exists = exists().where(
            WeeklyDigest.client_id == ClientReportPolicy.client_id,
            or_(
                and_(ClientReportPolicy.cadence == "weekly", WeeklyDigest.period_start == weekly_start, WeeklyDigest.period_end == weekly_end),
                and_(ClientReportPolicy.cadence == "monthly", WeeklyDigest.period_start == monthly_start, WeeklyDigest.period_end == monthly_end),
            ),
        )
        report_live = exists().where(
            ClientReportPolicy.client_id == Notification.entity_id,
            Client.id == ClientReportPolicy.client_id,
            _report_source_clause(user_id),
            ~digest_exists,
            Notification.dedupe_key == case(
                (ClientReportPolicy.cadence == "weekly", func.concat("report_pending:client:", ClientReportPolicy.client_id, ":weekly:", func.to_char(weekly_start, "YYYY-MM-DD"), ":", func.to_char(weekly_end, "YYYY-MM-DD"))),
                else_=func.concat("report_pending:client:", ClientReportPolicy.client_id, ":monthly:", func.to_char(monthly_start, "YYYY-MM-DD"), ":", func.to_char(monthly_end, "YYYY-MM-DD")),
            ),
        )
    unsent_filters = [
        ClientReportPolicy.client_id == Notification.entity_id,
        Client.id == ClientReportPolicy.client_id,
        _unsent_recipient_clause(user_id),
    ]
    if current_only:
        month_start, month_end = policy_digest_period("monthly", today=business_today(now=now))
        unsent_filters.extend((
            _monthly_cycle_clause(),
            ~delivery_confirmed_clause(ClientReportPolicy.client_id, month_start, month_end),
            Notification.dedupe_key == func.concat(
                f"{REPORT_UNSENT}:client:", ClientReportPolicy.client_id,
                f":monthly:{month_start.isoformat()}:{month_end.isoformat()}",
            ),
        ))
    unsent_live = exists().where(*unsent_filters)
    clause = and_(
        Notification.user_id == user_id,
        Notification.type.in_(REPORT_CONDITIONS),
        or_(
            and_(Notification.type == "report_pending", Notification.entity_type == "client", report_live),
            and_(Notification.type == REPORT_UNSENT, Notification.entity_type == "client", unsent_live),
            and_(Notification.type == "delivery_failed", Notification.entity_type == "delivery", delivery_live),
        ),
    )
    # The collector owns exact-period comparison; this predicate intentionally
    # remains SQL-only so route reads can revoke stale source access immediately.
    return clause


async def collect_report_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    """Collect report and delivery conditions in bounded reads, without writes."""
    today = business_today(now=now)
    policy_rows = (await db.execute(
        select(ClientReportPolicy.client_id, ClientReportPolicy.cadence, Client.name)
        .join(Client, Client.id == ClientReportPolicy.client_id)
        .where(_report_source_clause(user_id))
    )).all()

    periods = {
        row.client_id: (row.cadence.value if hasattr(row.cadence, "value") else str(row.cadence), *policy_digest_period(
            row.cadence.value if hasattr(row.cadence, "value") else str(row.cadence), today=today
        ))
        for row in policy_rows
    }
    matching_digests: set[tuple[int, object, object]] = set()
    if periods:
        coverage = or_(*[
            and_(WeeklyDigest.client_id == client_id, WeeklyDigest.period_start == start, WeeklyDigest.period_end == end)
            for client_id, (_, start, end) in periods.items()
        ])
        matching_digests = {
            (row.client_id, row.period_start, row.period_end)
            for row in (await db.execute(select(WeeklyDigest.client_id, WeeklyDigest.period_start, WeeklyDigest.period_end).where(coverage))).all()
        }

    conditions: dict[str, Condition] = {}
    for row in policy_rows:
        cadence, start, end = periods[row.client_id]
        if (row.client_id, start, end) in matching_digests:
            continue
        cadence_label = "semanal" if cadence == "weekly" else "mensual"
        key = f"report_pending:client:{row.client_id}:{cadence}:{start.isoformat()}:{end.isoformat()}"
        conditions[key] = Condition(
            key=key, kind="report_pending", entity_id=row.client_id, entity_type="client", entity_key=str(row.client_id),
            title=f"Resumen pendiente: {row.name}"[:255],
            message=f"Falta preparar el resumen {cadence_label} del {start:%d/%m/%Y} al {end:%d/%m/%Y}.",
            href=f"/digests?client_id={row.client_id}&period_start={start.isoformat()}&period_end={end.isoformat()}", fingerprint=_fingerprint(key),
        )

    conditions.update(await _collect_unsent_monthly(db, user_id, today, skip_clients={
        condition.entity_id for condition in conditions.values() if condition.kind == "report_pending"
    }))

    replacement = aliased(Delivery)
    delivery_rows = (await db.execute(
        select(Delivery.id, Delivery.status, Delivery.source_id)
        .where(
            _delivery_source_clause(user_id),
            Delivery.status.in_(("failed", "uncertain")),
            ~exists().where(replacement.resend_of == Delivery.id),
        )
    )).all()
    for row in delivery_rows:
        key = f"delivery_failed:delivery:{row.id}:{row.status}"
        state = "No se confirmó el envío; revisa el recibo antes de reenviar." if row.status == "uncertain" else "El envío falló; revisa el recibo y decide si reintentar."
        conditions[key] = Condition(
            key=key, kind="delivery_failed", entity_id=None, entity_type="delivery", entity_key=row.id,
            title="Envío sin confirmación" if row.status == "uncertain" else "Envío fallido", message=state,
            href=f"/deliveries/{row.id}", fingerprint=_fingerprint(key), severity="warning",
        )
    return conditions


async def _collect_unsent_monthly(db, user_id: int, today, *, skip_clients: set[int]) -> dict[str, Condition]:
    """From day 1, every monthly client whose last month nobody confirmed as delivered.

    A responsible already told to prepare the digest (``report_pending``) does
    not get a second notice for the same client until a version exists.
    """
    start, end = policy_digest_period("monthly", today=today)
    rows = (await db.execute(
        select(Client.id, Client.name)
        .join(ClientReportPolicy, ClientReportPolicy.client_id == Client.id)
        .where(
            _monthly_cycle_clause(),
            _unsent_recipient_clause(user_id),
            ~delivery_confirmed_clause(Client.id, start, end),
        )
        .order_by(Client.id)
    )).all()
    rows = [row for row in rows if row.id not in skip_clients]
    if not rows:
        return {}
    latest: dict[int, int] = {}
    for version in (await db.execute(
        select(WeeklyDigest.client_id, WeeklyDigest.id)
        .where(
            WeeklyDigest.client_id.in_([row.id for row in rows]),
            WeeklyDigest.period_start == start,
            WeeklyDigest.period_end == end,
        )
        .order_by(WeeklyDigest.created_at, WeeklyDigest.id)
    )).all():
        latest[version.client_id] = version.id

    month = format_month(start)
    conditions: dict[str, Condition] = {}
    for row in rows:
        key = _unsent_key(row.id, start, end)
        digest_id = latest.get(row.id)
        if digest_id is None:
            message = f"Falta preparar y entregar el resumen de {month}."
            href = f"/digests?client_id={row.id}&period_start={start.isoformat()}&period_end={end.isoformat()}"
        else:
            message = f"El resumen de {month} está preparado (versión #{digest_id}), pero nadie ha confirmado que se entregó al cliente."
            href = f"/digests/{digest_id}/edit"
        conditions[key] = Condition(
            key=key, kind=REPORT_UNSENT, entity_id=row.id, entity_type="client", entity_key=str(row.id),
            title=f"Resumen mensual sin entregar: {row.name}"[:255], message=message, href=href,
            fingerprint=_fingerprint(key),
        )
    return conditions
