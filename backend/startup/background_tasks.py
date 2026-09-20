"""Background async loops launched at startup.

Each operation performs one cycle. ``start_background_tasks`` wraps enabled
operations in the durable singleton coordinator and the lifespan cancels those
loops on shutdown.
"""
import asyncio
import logging

from backend.config import settings
from backend.services.temporal import business_today, business_zone, utc_now_naive

BUSINESS_TZ = business_zone()


def _log_task_error(t: asyncio.Task) -> None:
    if not t.cancelled() and (exc := t.exception()):
        logging.error("Background task %s failed: %s", t.get_name(), exc)


# ── Engine sync ──────────────────────────────────────────────

async def _engine_sync_once():
    from backend.services.engine_sync_service import sync_engine_metrics
    from backend.services.job_runtime import JobFailure

    result = await sync_engine_metrics()
    if result.get("detail") == "not configured":
        raise JobFailure("provider_unavailable")
    if result.get("failed", 0):
        raise JobFailure("partial_failure")


# ── Holded sync ──────────────────────────────────────────────

async def _holded_sync_once():
    """Run one daily pass over Holded contacts, invoices and expenses."""
    from backend.api.routes.holded import sync_contacts, sync_invoices, sync_expenses
    from backend.db.database import async_session

    from backend.services.job_runtime import JobFailure

    logging.info("Holded auto-sync starting...")
    failures = 0
    for fn in (sync_contacts, sync_invoices, sync_expenses):
        try:
            # A failed stage must not poison the next stage's transaction.
            async with async_session() as session:
                await fn(session=session, user=None)
        except Exception as exc:
            failures += 1
            logging.error("Holded auto-sync %s error: %s", fn.__name__, type(exc).__name__)
    if failures:
        raise JobFailure("partial_failure")
    logging.info("Holded auto-sync complete.")


# ── Recurring task generation ────────────────────────────────

async def _generate_recurring_instances():
    """Create task instances from recurring templates for today."""
    from backend.db.database import async_session
    from backend.services.recurrence import generate_recurring_instances

    async with async_session() as session:
        created = await generate_recurring_instances(session)
        if created:
            logging.info("Generated %d recurring task instance(s) for %s", created, business_today())


async def _check_overdue_tasks():
    """Check for overdue tasks and fire automation triggers."""
    from datetime import date as date_type, datetime as dt_type
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import Task, TaskStatus

    today = business_today()
    today_midnight = dt_type.combine(today, dt_type.min.time())

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.status.notin_([TaskStatus.completed]),
                Task.due_date < today_midnight,
            )
        )
        overdue_tasks = result.scalars().all()

        if not overdue_tasks:
            return

        count = 0
        failures = 0
        for task in overdue_tasks:
            try:
                from backend.api.routes.automations import execute_automations
                await execute_automations("task_overdue", {
                    "task_id": task.id,
                    "task_title": task.title,
                    "project_id": task.project_id,
                    "client_id": task.client_id,
                    "assigned_to": task.assigned_to,
                    "due_date": str(task.due_date),
                    "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                }, session)
                count += 1
            except Exception as exc:
                failures += 1
                logging.warning("Overdue automation failed for task %d: %s", task.id, exc)

        logging.info("Checked %d overdue tasks, triggered %d automations.", len(overdue_tasks), count)
        if failures:
            from backend.services.job_runtime import JobFailure

            raise JobFailure("partial_failure")


async def _reset_advanced_tasks():
    """Devolver a "En curso" las tareas marcadas como "Avanzada" días anteriores.

    "Avanzada" significa "hoy he avanzado en esto, mañana sigo": cierra la tarea
    en el informe diario de hoy pero no la da por terminada. La barrida se hace
    por ``advanced_at < today`` en vez de "todo lo que esté advanced", de modo
    que si el proceso estuvo caído a medianoche la siguiente ejecución (incluido
    el arranque) recupera el retraso sin dejar tareas congeladas en Avanzada.
    """
    from sqlalchemy import select, update
    from backend.db.database import async_session
    from backend.db.models import Task, TaskStatus

    today = business_today()

    async with async_session() as session:
        eligible = (
            Task.status == TaskStatus.advanced,
            (Task.advanced_at.is_(None)) | (Task.advanced_at < today),
        )
        # Use the same ordering as bulk edits, Undo and incident reconciliation.
        # PostgreSQL rechecks eligibility after waiting for a concurrent writer.
        ids = list(
            (
                await session.execute(
                    select(Task.id).where(*eligible).order_by(Task.id).with_for_update()
                )
            ).scalars()
        )
        if not ids:
            return
        result = await session.execute(
            update(Task)
            .where(Task.id.in_(ids), *eligible)
            .values(status=TaskStatus.in_progress, advanced_at=None)
        )
        if result.rowcount:
            await session.commit()
            logging.info(
                "Reset %d 'Avanzada' task(s) back to 'En curso'.", result.rowcount
            )


def _is_qa_user(user) -> bool:
    """Return True for test/QA users that should never get notifications."""
    _name_lower = (user.full_name or "").lower()
    _short_lower = (user.short_name or "").lower()
    _email_lower = (user.email or "").lower()
    return (
        "example.com" in _email_lower
        or _email_lower.startswith("test@")
        or _email_lower.startswith("qa-")
        or _email_lower.startswith("qa_")
        or _name_lower.startswith("qa ")
        or _name_lower.startswith("qa_")
        or _short_lower.startswith("qa ")
        or _short_lower.startswith("qa_")
        or "audit" in _name_lower
        or "test" in _name_lower
    )


# ── Google Calendar sync + meeting alerts ───────────────────

async def _sync_calendars_once():
    """Run one isolated pass over every connected calendar."""
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import User
    from backend.api.routes.google_calendar import sync_user_events
    from backend.services.job_runtime import JobFailure

    failures = 0
    try:
        async with async_session() as db:
            user_ids = (await db.scalars(select(User.id).where(
                User.is_active.is_(True),
                User.google_calendar_connected.is_(True),
                User.google_refresh_token.isnot(None),
            ))).all()
    except Exception as exc:
        raise JobFailure("execution_failed") from exc
    for user_id in user_ids:
        try:
            async with async_session() as db:
                user = await db.get(User, user_id)
                if user is None or _is_qa_user(user):
                    continue
                count = await sync_user_events(db, user)
                if count:
                    logging.debug("Calendar sync: %d events for user %s", count, user_id)
        except Exception as exc:
            failures += 1
            logging.warning("Calendar sync failed for user %s: %s", user_id, type(exc).__name__)
    if failures:
        raise JobFailure("partial_failure")


# ── Retention cleanup ───────────────────────────────────────

async def _retention_cleanup_once():
    """Prune append-only logging tables to keep the DB small.

    Runs once shortly after startup and then every 24h. Logs and
    audit-style rows older than 90 days are deleted; notifications
    that have already been read get a 30-day window.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import delete
    from backend.db.database import async_session
    from backend.db.models import AuditLog, ChangeLog, SyncLog, HoldedSyncLog, AutomationLog, Notification

    now = utc_now_naive()
    cutoff_90d = now - timedelta(days=90)
    cutoff_30d = now - timedelta(days=30)

    async with async_session() as db:
        total = 0
        # Tables with created_at via TimestampMixin
        for model in (AuditLog, ChangeLog, SyncLog, AutomationLog):
            r = await db.execute(delete(model).where(model.created_at < cutoff_90d))
            total += r.rowcount or 0
        # HoldedSyncLog doesn't use TimestampMixin; key off started_at
        r = await db.execute(
            delete(HoldedSyncLog).where(HoldedSyncLog.started_at < cutoff_90d)
        )
        total += r.rowcount or 0
        # Notifications already read: shorter 30-day window
        r = await db.execute(
            delete(Notification).where(
                Notification.is_read.is_(True),
                Notification.created_at < cutoff_30d,
                Notification.dedupe_key.is_(None),
            )
        )
        total += r.rowcount or 0
        await db.commit()
        logging.info(
            "Retention sweep: deleted %d rows (logs >90d, read notifications >30d)",
            total,
        )


# ── Coordinated runtime ──────────────────────────────────────

async def _incident_once():
    from backend.db.database import async_session
    from backend.services.incidents import reconcile_all
    from backend.services.job_runtime import JobFailure

    result = await reconcile_all(async_session)
    if result["failed"]:
        raise JobFailure("partial_failure")


async def _scheduled_communications_once():
    from backend.db.database import async_session
    from backend.services.scheduled_communications import run_scheduler_once

    await run_scheduler_once(async_session, raise_on_error=True)


async def _inbox_classification_once():
    from backend.services.inbox_processing import run_inbox_classification_once
    from backend.services.job_runtime import JobFailure

    if await run_inbox_classification_once():
        raise JobFailure("partial_failure")


async def _coordinated_job_loop(definition, operation):
    """Poll durable due state; ``operation`` performs exactly one job cycle."""
    from backend.db.database import engine
    from backend.services.job_runtime import run_job

    while True:
        try:
            await run_job(engine, definition.spec, operation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # run_job already persisted a sanitized failure code.
            logging.error(
                "Background job %s failed (%s)",
                definition.spec.key,
                type(exc).__name__,
            )
        await asyncio.sleep(min(60, definition.spec.interval_seconds))


# ── Public API ───────────────────────────────────────────────

def start_background_tasks() -> list[asyncio.Task]:
    """Create coordinated background tasks for enabled catalog entries."""
    from backend.services.job_catalog import job_definitions

    tasks: list[asyncio.Task] = []
    definitions = {item.spec.key: item for item in job_definitions()}
    operations = {
        "incidents": ("operational-incidents", _incident_once),
        "engine": ("engine-sync", _engine_sync_once),
        "holded": ("holded-sync", _holded_sync_once),
        "advanced_reset": ("advanced-reset", _reset_advanced_tasks),
        "recurrence": ("recurring-reconcile", _generate_recurring_instances),
        "overdue_automations": ("overdue-automations", _check_overdue_tasks),
        "scheduled_communications": (
            "scheduled-communications", _scheduled_communications_once,
        ),
        "calendar": ("calendar-sync", _sync_calendars_once),
        "retention": ("retention-cleanup", _retention_cleanup_once),
        "inbox_classification": ("inbox-classification", _inbox_classification_once),
    }

    for key, (task_name, operation) in operations.items():
        definition = definitions[key]
        if not definition.enabled:
            continue
        task = asyncio.create_task(
            _coordinated_job_loop(definition, operation), name=task_name,
        )
        task.add_done_callback(_log_task_error)
        tasks.append(task)

    if settings.DELIVERY_WORKER_ENABLED:
        from backend.services.deliveries import delivery_loop

        task = asyncio.create_task(delivery_loop(), name="manual-deliveries")
        task.add_done_callback(_log_task_error)
        tasks.append(task)

    return tasks
