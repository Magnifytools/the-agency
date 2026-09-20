"""Small, privacy-safe operational aggregates for the admin usage screen."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ACTIVE_TASK_STATUSES,
    ChangeLog,
    CommandReceipt,
    DailyUpdate,
    Delivery,
    Notification,
    Task,
    TaskStatus,
)
from backend.services.temporal import utc_now_naive


def _count(value) -> int:
    return int(value or 0)


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _iso_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds") + "Z"


async def collect_operational_usage(
    db: AsyncSession, *, days: int, now: datetime | None = None,
) -> dict:
    end = now or utc_now_naive()
    start = end - timedelta(days=days)
    active_work = (
        Task.retired_at.is_(None),
        Task.is_recurring.is_(False),
        Task.status.in_(ACTIVE_TASK_STATUSES),
    )
    work = (await db.execute(select(
        func.count(Task.id),
        func.count(Task.id).filter(Task.project_id.isnot(None)),
        func.count(Task.id).filter(or_(
            Task.scheduled_date.isnot(None), Task.due_date.isnot(None),
            Task.status == TaskStatus.waiting,
        )),
    ).where(*active_work))).one()
    work_total, with_project, planned = map(_count, work)

    incidents = (await db.execute(select(
        func.count(Notification.id).filter(Notification.incident_state == "active"),
        func.count(Notification.id).filter(Notification.incident_state == "snoozed"),
        func.count(Notification.id).filter(Notification.incident_state == "dismissed"),
        func.count(Notification.id).filter(
            Notification.incident_resolved_at >= start,
            Notification.incident_resolved_at < end,
        ),
    ).where(Notification.incident_state.isnot(None)))).one()

    daily_user_days = select(DailyUpdate.user_id, DailyUpdate.date).where(
        DailyUpdate.created_at >= start, DailyUpdate.created_at < end,
    ).distinct().subquery()
    daily = (await db.execute(select(
        func.count(DailyUpdate.id), func.count(distinct(DailyUpdate.user_id)),
    ).where(DailyUpdate.created_at >= start, DailyUpdate.created_at < end))).one()
    user_days = _count(await db.scalar(select(func.count()).select_from(daily_user_days)))

    commands = (await db.execute(select(
        func.count(CommandReceipt.id).filter(CommandReceipt.status == "executed"),
        func.count(CommandReceipt.id).filter(CommandReceipt.status == "failed"),
        func.count(CommandReceipt.id).filter(CommandReceipt.status == "needs_input"),
        func.count(CommandReceipt.id).filter(CommandReceipt.status == "needs_review"),
        func.count(CommandReceipt.id).filter(ChangeLog.undone_at.isnot(None)),
        func.count(CommandReceipt.id).filter(CommandReceipt.channel == "app"),
        func.count(CommandReceipt.id).filter(CommandReceipt.channel == "extension"),
        func.count(CommandReceipt.id).filter(CommandReceipt.channel.notin_(("app", "extension"))),
    ).outerjoin(ChangeLog, CommandReceipt.change_log_id == ChangeLog.id).where(
        CommandReceipt.created_at >= start, CommandReceipt.created_at < end,
    ))).one()
    executed, failed, needs_input, needs_review, undone, app, extension, unknown = map(_count, commands)

    deliveries = (await db.execute(select(*[
        func.count(Delivery.id).filter(Delivery.status == status)
        for status in ("sent", "failed", "uncertain", "expired", "cancelled", "pending", "sending")
    ]).where(Delivery.created_at >= start, Delivery.created_at < end))).one()
    sent, delivery_failed, uncertain, expired, cancelled, pending, sending = map(_count, deliveries)
    command_terminal = executed + failed
    delivery_terminal = sent + delivery_failed + uncertain + expired

    return {
        "as_of": _iso_utc(end),
        "window": {"days": days, "start": _iso_utc(start), "end": _iso_utc(end)},
        "work_context": {
            "total": work_total, "with_project": with_project,
            "without_project": work_total - with_project,
            "coverage_percent": _percent(with_project, work_total),
        },
        "work_planning": {
            "total": work_total, "planned_or_waiting": planned,
            "unplanned": work_total - planned,
            "coverage_percent": _percent(planned, work_total),
        },
        "incidents": dict(zip(
            ("active", "snoozed", "dismissed", "resolved_in_window"),
            map(_count, incidents), strict=True,
        )),
        "dailys": {"updates": _count(daily[0]), "authors": _count(daily[1]), "user_days": user_days},
        "commands": {
            "executed": executed, "failed": failed, "needs_input": needs_input,
            "needs_review": needs_review, "undone": undone,
            "terminal_total": command_terminal,
            "success_percent": _percent(executed, command_terminal),
            "by_channel": {"app": app, "extension": extension, "unknown": unknown},
        },
        "deliveries": {
            "sent": sent, "failed": delivery_failed, "uncertain": uncertain,
            "expired": expired, "cancelled": cancelled, "pending": pending, "sending": sending,
            "terminal_total": delivery_terminal,
            "confirmation_percent": _percent(sent, delivery_terminal),
        },
    }
