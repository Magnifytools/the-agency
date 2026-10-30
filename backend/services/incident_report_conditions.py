"""Bounded, read-only operational conditions for report policies and deliveries."""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, case, exists, false, func, or_, select
from sqlalchemy.orm import aliased

from backend.core.modules import is_enabled
from backend.db.models import (
    Client,
    ClientLocalReport,
    ClientLocalReportConfig,
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
    User,
    UserRole,
    WeeklyDigest,
)
from backend.services.digest_periods import CADENCES, enabled_cadences, format_month, policy_digest_period
from backend.services.incident_conditions import Condition, module_permission
from backend.services.manual_communications import KINDS as MANUAL_KINDS
from backend.services.scheduled_communications import KINDS as SCHEDULED_KINDS
from backend.services.temporal import business_today

REPORT_UNSENT = "report_unsent"
REPORT_CONDITIONS = ("report_pending", "delivery_failed", REPORT_UNSENT)


_CADENCE_FLAGS = {
    "monthly": ClientReportPolicy.monthly_enabled,
    "weekly": ClientReportPolicy.weekly_enabled,
}


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def _report_source_clause(user_id: int):
    """A policy is actionable only by its still-authorized explicit owner."""
    if not is_enabled("digests"):
        return false()
    return and_(
        or_(ClientReportPolicy.weekly_enabled.is_(True), ClientReportPolicy.monthly_enabled.is_(True)),
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
    """Active external clients whose policy has the monthly report on."""
    return and_(
        ClientReportPolicy.monthly_enabled.is_(True),
        Client.status == ClientStatus.active,
        Client.is_internal.is_(False),
    )


def delivery_is_confirmed():
    """The digest version's latest external delivery event is a confirmation.

    The external delivery event is the only proof that a digest reached the
    client; ``DigestStatus.sent`` is a legacy label nobody records evidence for.
    A later revocation cancels the confirmation.
    """
    latest_action = (
        select(DigestExternalDeliveryEvent.action)
        .where(DigestExternalDeliveryEvent.digest_id == WeeklyDigest.id)
        .order_by(DigestExternalDeliveryEvent.created_at.desc(), DigestExternalDeliveryEvent.id.desc())
        .limit(1)
        .correlate(WeeklyDigest)
        .scalar_subquery()
    )
    return latest_action == ExternalDeliveryAction.confirmed


def local_report_clause(client_id, month_start, month_end, *, delivered: bool):
    """El informe SEO local de ese mes hace de informe mensual del cliente.

    Es del mes en que EMPIEZA (el de octubre de 2026 va del 1 al 26) y está
    entregado cuando alguien lo marcó en su pestaña (``delivered_at``).
    """
    filters = [
        ClientLocalReport.client_id == client_id,
        ClientLocalReport.period_start >= month_start,
        ClientLocalReport.period_start <= month_end,
    ]
    if delivered:
        filters.append(ClientLocalReport.delivered_at.isnot(None))
    return exists().where(*filters)


async def _local_reports(db, client_ids: list[int], month_start, month_end) -> dict[int, int | None]:
    """Clientes con informe SEO local configurado → su última versión del mes (o None)."""
    if not client_ids:
        return {}
    rows = (await db.execute(
        select(ClientLocalReportConfig.client_id, func.max(ClientLocalReport.id))
        .outerjoin(ClientLocalReport, and_(
            ClientLocalReport.client_id == ClientLocalReportConfig.client_id,
            ClientLocalReport.period_start.between(month_start, month_end),
        ))
        .where(ClientLocalReportConfig.client_id.in_(client_ids))
        .group_by(ClientLocalReportConfig.client_id)
    )).all()
    return {client_id: version_id for client_id, version_id in rows}


def delivery_confirmed_clause(client_id, period_start, period_end):
    """Some version of the month has, as its latest event, a confirmed delivery,
    or the client's SEO local report of that month was delivered."""
    return or_(
        exists().where(
            WeeklyDigest.client_id == client_id,
            WeeklyDigest.period_start == period_start,
            WeeklyDigest.period_end == period_end,
            delivery_is_confirmed(),
        ),
        local_report_clause(client_id, period_start, period_end, delivered=True),
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

        def pending_live(cadence: str):
            # Una rama por cadencia: sigue viva mientras esa cadencia esté
            # encendida y falte el resumen de su periodo actual.
            start, end = policy_digest_period(cadence, today=today)
            prepared = [~exists().where(
                WeeklyDigest.client_id == ClientReportPolicy.client_id,
                WeeklyDigest.period_start == start,
                WeeklyDigest.period_end == end,
            )]
            if cadence == "monthly":
                prepared.append(~local_report_clause(ClientReportPolicy.client_id, start, end, delivered=False))
            return exists().where(
                ClientReportPolicy.client_id == Notification.entity_id,
                Client.id == ClientReportPolicy.client_id,
                _report_source_clause(user_id),
                _CADENCE_FLAGS[cadence].is_(True),
                *prepared,
                Notification.dedupe_key == func.concat(
                    "report_pending:client:", ClientReportPolicy.client_id,
                    f":{cadence}:{start.isoformat()}:{end.isoformat()}",
                ),
            )

        report_live = or_(*(pending_live(cadence) for cadence in CADENCES))
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
        select(ClientReportPolicy, Client.name)
        .join(Client, Client.id == ClientReportPolicy.client_id)
        .where(_report_source_clause(user_id))
    )).all()

    periods = {cadence: policy_digest_period(cadence, today=today) for cadence in CADENCES}
    # Un par (cliente, cadencia) por cada cadencia encendida.
    pairs = [
        (policy.client_id, name, cadence)
        for policy, name in policy_rows
        for cadence in enabled_cadences(policy)
    ]
    matching_digests: set[tuple[int, object, object]] = set()
    local_clients: set[int] = set()
    if pairs:
        coverage = or_(*[
            and_(WeeklyDigest.client_id == client_id, WeeklyDigest.period_start == periods[cadence][0], WeeklyDigest.period_end == periods[cadence][1])
            for client_id, _, cadence in pairs
        ])
        matching_digests = {
            (row.client_id, row.period_start, row.period_end)
            for row in (await db.execute(select(WeeklyDigest.client_id, WeeklyDigest.period_start, WeeklyDigest.period_end).where(coverage))).all()
        }
        monthly_ids = [client_id for client_id, _, cadence in pairs if cadence == "monthly"]
        if monthly_ids:
            month_start, month_end = periods["monthly"]
            for client_id, version_id in (await _local_reports(db, monthly_ids, month_start, month_end)).items():
                local_clients.add(client_id)
                if version_id is not None:
                    matching_digests.add((client_id, month_start, month_end))

    conditions: dict[str, Condition] = {}
    monthly_pending: set[int] = set()
    for client_id, name, cadence in pairs:
        start, end = periods[cadence]
        if (client_id, start, end) in matching_digests:
            continue
        if cadence == "monthly":
            monthly_pending.add(client_id)
        local = cadence == "monthly" and client_id in local_clients
        what = ("el informe SEO local" if local else "el informe mensual") if cadence == "monthly" else "el seguimiento semanal"
        key = f"report_pending:client:{client_id}:{cadence}:{start.isoformat()}:{end.isoformat()}"
        href = (f"/clients/{client_id}?tab=informe_local" if local else
                f"/digests?client_id={client_id}&period_start={start.isoformat()}&period_end={end.isoformat()}")
        conditions[key] = Condition(
            key=key, kind="report_pending", entity_id=client_id, entity_type="client", entity_key=str(client_id),
            title=f"Resumen pendiente: {name}"[:255],
            message=f"Falta preparar {what} del {start:%d/%m/%Y} al {end:%d/%m/%Y}.",
            href=href, fingerprint=_fingerprint(key),
        )

    # Sólo un pendiente MENSUAL tapa el aviso de mensual sin entregar: el
    # seguimiento semanal pendiente no dice nada del mes.
    conditions.update(await _collect_unsent_monthly(db, user_id, today, skip_clients=monthly_pending))

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


async def unsent_monthly_clients(db, user_id: int, today):
    """Monthly clients of last month with no confirmed delivery, as this user sees them.

    Admins see every one; a responsible sees theirs while they can still
    prepare digests. Returns ``(period_start, period_end, rows)`` with
    ``rows`` of ``(id, name)`` ordered by client id.
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
    return start, end, rows


async def _collect_unsent_monthly(db, user_id: int, today, *, skip_clients: set[int]) -> dict[str, Condition]:
    """From day 1, every monthly client whose last month nobody confirmed as delivered.

    A responsible already told to prepare the digest (``report_pending``) does
    not get a second notice for the same client until a version exists.
    """
    start, end, rows = await unsent_monthly_clients(db, user_id, today)
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
    local = await _local_reports(db, [row.id for row in rows], start, end)

    month = format_month(start)
    conditions: dict[str, Condition] = {}
    for row in rows:
        key = _unsent_key(row.id, start, end)
        digest_id = latest.get(row.id)
        if digest_id is None and row.id in local:
            href = f"/clients/{row.id}?tab=informe_local"
            if local[row.id] is None:
                message = f"Falta preparar y entregar el informe SEO local de {month}."
            else:
                message = (f"El informe SEO local de {month} está preparado (versión #{local[row.id]}), "
                           "pero nadie lo ha marcado como entregado.")
        elif digest_id is None:
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
