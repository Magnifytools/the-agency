"""Background async loops launched at startup.

Each function runs in an infinite loop as an asyncio.Task. They are
created by start_background_tasks() and cancelled on shutdown.

Extracted from main.py to keep the entry point lean.
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

async def _engine_sync_loop():
    from backend.services.engine_sync_service import sync_engine_metrics
    await asyncio.sleep(60)  # initial delay
    while True:
        try:
            await sync_engine_metrics()
        except Exception as e:
            logging.error("Engine sync loop error: %s", e)
        await asyncio.sleep(settings.ENGINE_SYNC_INTERVAL_HOURS * 3600)


# ── Holded sync ──────────────────────────────────────────────

async def _holded_sync_loop():
    """Sync Holded contacts, invoices and expenses every 6 hours."""
    from backend.api.routes.holded import sync_contacts, sync_invoices, sync_expenses
    from backend.db.database import async_session

    await asyncio.sleep(300)  # 5 min initial delay to let DB settle
    while True:
        logging.info("Holded auto-sync starting...")
        try:
            async with async_session() as session:
                for fn in (sync_contacts, sync_invoices, sync_expenses):
                    try:
                        await fn(session=session, user=None)
                    except Exception as e:
                        logging.error("Holded auto-sync %s error: %s", fn.__name__, e)
            logging.info("Holded auto-sync complete.")
        except Exception as e:
            logging.error("Holded auto-sync session error: %s", e)
        await asyncio.sleep(24 * 3600)  # every 24 hours


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
                logging.warning("Overdue automation failed for task %d: %s", task.id, exc)

        logging.info("Checked %d overdue tasks, triggered %d automations.", len(overdue_tasks), count)


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


async def _recurring_midnight_loop():
    """Background loop that generates recurring task instances and checks overdue tasks at midnight."""
    from datetime import datetime, timedelta, timezone

    # Catch-up al arrancar: si el proceso estuvo caído a medianoche, las tareas
    # "Avanzada" de ayer siguen bloqueadas hasta la próxima medianoche.
    try:
        await _reset_advanced_tasks()
    except Exception as exc:
        logging.error("Advanced task reset (startup catch-up) failed: %s", exc)
    while True:
        now = datetime.now(BUSINESS_TZ)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        wait_seconds = (
            tomorrow.astimezone(timezone.utc) - now.astimezone(timezone.utc)
        ).total_seconds()
        logging.info("Recurring task loop: next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await _reset_advanced_tasks()
        except Exception as exc:
            logging.error("Advanced task reset failed: %s", exc)
        try:
            await _generate_recurring_instances()
        except Exception as exc:
            logging.error("Recurring task generation failed: %s", exc)
        try:
            await _check_overdue_tasks()
        except Exception as exc:
            logging.error("Overdue task check failed: %s", exc)


async def _recurring_reconciliation_loop():
    """Reconcile today's occurrence at startup and periodically after resumes."""
    while True:
        try:
            await _generate_recurring_instances()
        except Exception as exc:
            logging.error("Recurring task reconciliation failed: %s", exc)
        await asyncio.sleep(300)


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


def _time_in_window(current_time: str, target: str, window_minutes: int = 5) -> bool:
    """Check if current_time (HH:MM) is within [target, target+window)."""
    ch, cm = int(current_time[:2]), int(current_time[3:])
    th, tm = int(target[:2]), int(target[3:])
    current_total = ch * 60 + cm
    target_total = th * 60 + tm
    return 0 <= (current_total - target_total) < window_minutes


# ── Google Calendar sync + meeting alerts ───────────────────

async def _calendar_sync_loop():
    """Sync Google Calendar events every 15 minutes."""
    from datetime import datetime
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import User
    from backend.api.routes.google_calendar import sync_user_events

    while True:
        try:
            async with async_session() as db:
                user_ids = (await db.scalars(select(User.id).where(
                    User.is_active.is_(True),
                    User.google_calendar_connected.is_(True),
                    User.google_refresh_token.isnot(None),
                ))).all()
            for user_id in user_ids:
                try:
                    # A failed provider/transaction must not poison the next user's sync.
                    async with async_session() as db:
                        user = await db.get(User, user_id)
                        if user is None or _is_qa_user(user):
                            continue
                        count = await sync_user_events(db, user)
                        if count:
                            logging.debug("Calendar sync: %d events for user %s", count, user_id)
                except Exception as e:
                    logging.warning("Calendar sync failed for user %s: %s", user_id, e)
        except Exception as e:
            logging.error("Calendar sync loop error: %s", e)
        await asyncio.sleep(900)  # First full reconciliation runs immediately.


# ── Retention cleanup ───────────────────────────────────────

async def _retention_cleanup_loop():
    """Prune append-only logging tables to keep the DB small.

    Runs once shortly after startup and then every 24h. Logs and
    audit-style rows older than 90 days are deleted; notifications
    that have already been read get a 30-day window.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import delete
    from backend.db.database import async_session
    from backend.db.models import AuditLog, ChangeLog, SyncLog, HoldedSyncLog, AutomationLog, Notification

    # Small initial delay so the rest of the boot finishes first.
    await asyncio.sleep(60)

    while True:
        try:
            now = utc_now_naive()
            cutoff_90d = now - timedelta(days=90)
            cutoff_30d = now - timedelta(days=30)

            async with async_session() as db:
                total = 0
                # Tables with created_at via TimestampMixin
                for model in (AuditLog, ChangeLog, SyncLog, AutomationLog):
                    r = await db.execute(
                        delete(model).where(model.created_at < cutoff_90d)
                    )
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
                logging.info("Retention sweep: deleted %d rows (logs >90d, read notifications >30d)", total)
        except Exception as e:
            logging.error("Retention cleanup loop error: %s", e)

        await asyncio.sleep(24 * 3600)  # daily


# ── Public API ───────────────────────────────────────────────

def start_background_tasks() -> list[asyncio.Task]:
    """Create and return all background asyncio.Tasks.

    The caller (lifespan) is responsible for cancelling them on shutdown.
    """
    tasks: list[asyncio.Task] = []

    if settings.INCIDENTS_ENABLED:
        from backend.services.incidents import incident_loop
        t = asyncio.create_task(incident_loop(), name="operational-incidents")
        t.add_done_callback(_log_task_error)
        tasks.append(t)

    if settings.DELIVERY_WORKER_ENABLED:
        from backend.services.deliveries import delivery_loop
        t = asyncio.create_task(delivery_loop(), name="manual-deliveries")
        t.add_done_callback(_log_task_error)
        tasks.append(t)

    if settings.ENGINE_SYNC_ENABLED and settings.ENGINE_API_URL:
        t = asyncio.create_task(_engine_sync_loop(), name="engine-sync")
        t.add_done_callback(_log_task_error)
        tasks.append(t)
        logging.info("Engine sync started (interval: %dh)", settings.ENGINE_SYNC_INTERVAL_HOURS)

    if settings.HOLDED_API_KEY:
        t = asyncio.create_task(_holded_sync_loop(), name="holded-sync")
        t.add_done_callback(_log_task_error)
        tasks.append(t)
        logging.info("Holded auto-sync started (every 24h).")

    t = asyncio.create_task(_recurring_midnight_loop(), name="recurring-gen")
    t.add_done_callback(_log_task_error)
    tasks.append(t)
    t = asyncio.create_task(_recurring_reconciliation_loop(), name="recurring-reconcile")
    t.add_done_callback(_log_task_error)
    tasks.append(t)

    if settings.SCHEDULED_COMMUNICATIONS_ENABLED:
        from backend.services.scheduled_communications import scheduler_loop
        t = asyncio.create_task(scheduler_loop(), name="scheduled-communications")
        t.add_done_callback(_log_task_error)
        tasks.append(t)

    if settings.GOOGLE_CLIENT_ID and settings.SCHEDULED_COMMUNICATIONS_ENABLED:
        t = asyncio.create_task(_calendar_sync_loop(), name="calendar-sync")
        t.add_done_callback(_log_task_error)
        tasks.append(t)

    t = asyncio.create_task(_retention_cleanup_loop(), name="retention-cleanup")
    t.add_done_callback(_log_task_error)
    tasks.append(t)
    logging.info("Retention cleanup loop started (logs >90d, read notifications >30d)")

    return tasks
