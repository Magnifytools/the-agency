"""Background async loops launched at startup.

Each function runs in an infinite loop as an asyncio.Task. They are
created by start_background_tasks() and cancelled on shutdown.

Extracted from main.py to keep the entry point lean.
"""
import asyncio
import logging
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")

from backend.config import settings


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
    from datetime import date as date_type
    from sqlalchemy import select, or_
    from backend.db.database import async_session
    from backend.db.models import Task, TaskStatus

    today = date_type.today()
    weekday = today.weekday()  # 0=Mon ... 4=Fri
    day_of_month = today.day

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.is_recurring == True,
                or_(Task.recurrence_end_date == None, Task.recurrence_end_date >= today),
            )
        )
        templates = result.scalars().all()

        created = 0
        for template in templates:
            should_create = False
            if template.recurrence_pattern == "daily":
                should_create = weekday < 5  # Mon-Fri only
            elif template.recurrence_pattern == "weekly":
                should_create = weekday == template.recurrence_day
            elif template.recurrence_pattern == "biweekly":
                week_num = today.isocalendar()[1]
                should_create = weekday == template.recurrence_day and week_num % 2 == 0
            elif template.recurrence_pattern == "monthly":
                should_create = day_of_month == template.recurrence_day

            if not should_create:
                continue

            # Check duplicate: instance with same parent + same scheduled_date
            dup = await session.execute(
                select(Task.id).where(
                    Task.recurring_parent_id == template.id,
                    Task.scheduled_date == today,
                )
            )
            if dup.scalar_one_or_none() is not None:
                continue

            new_task = Task(
                title=template.title,
                description=template.description,
                client_id=template.client_id,
                category_id=template.category_id,
                assigned_to=template.assigned_to,
                priority=template.priority,
                status=TaskStatus.pending,
                scheduled_date=today,
                due_date=today,
                recurring_parent_id=template.id,
                is_recurring=False,
            )
            session.add(new_task)
            created += 1

        if created:
            await session.commit()
            logging.info("Generated %d recurring task instance(s) for %s", created, today)


async def _check_overdue_tasks():
    """Check for overdue tasks and fire automation triggers."""
    from datetime import date as date_type, datetime as dt_type
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import Task, TaskStatus

    today = date_type.today()
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


async def _recurring_midnight_loop():
    """Background loop that generates recurring task instances and checks overdue tasks at midnight."""
    from datetime import datetime, timedelta

    while True:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        wait_seconds = (tomorrow - now).total_seconds()
        logging.info("Recurring task loop: next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await _generate_recurring_instances()
        except Exception as exc:
            logging.error("Recurring task generation failed: %s", exc)
        try:
            await _check_overdue_tasks()
        except Exception as exc:
            logging.error("Overdue task check failed: %s", exc)


# ── Billing reminders ────────────────────────────────────────

async def _billing_reminder_loop():
    """Daily check for projects with upcoming billing dates."""
    from datetime import datetime, timedelta
    while True:
        now = datetime.now()
        target = now.replace(hour=8, minute=1, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await _check_project_billing()
        except Exception as e:
            logging.error("Billing check error: %s", e)


async def _check_project_billing():
    """Create notifications for projects with upcoming or overdue billing."""
    from datetime import date, timedelta
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import Project, ProjectStatus, User, UserRole
    from backend.services.notification_service import create_notification, BILLING_REMINDER

    async with async_session() as db:
        today = date.today()
        threshold = today + timedelta(days=3)

        result = await db.execute(
            select(Project).where(
                Project.status.in_([ProjectStatus.active, ProjectStatus.completed]),
                Project.next_billing_date <= threshold,
                Project.next_billing_date.isnot(None),
            )
        )
        projects = result.scalars().all()
        if not projects:
            return

        admin_result = await db.execute(
            select(User).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        admin_ids = [u.id for u in admin_result.scalars().all()]

        for proj in projects:
            amt = float(proj.billing_amount) if proj.billing_amount else 0
            is_overdue = proj.next_billing_date <= today
            msg = (
                f"Factura vencida: {proj.name} ({amt}EUR) desde {proj.next_billing_date}"
                if is_overdue
                else f"Toca facturar {proj.name} ({amt}EUR) el {proj.next_billing_date}"
            )
            for admin_id in admin_ids:
                await create_notification(
                    db, user_id=admin_id, type=BILLING_REMINDER,
                    title=f"Facturación: {proj.name}",
                    message=msg,
                    link_url=f"/projects/{proj.id}",
                    entity_type="project", entity_id=proj.id,
                )
        await db.commit()
        logging.info("Billing check: %d projects notified.", len(projects))


# ── Daily reminders ──────────────────────────────────────────

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


async def _daily_reminders_loop():
    """Check every 5 minutes if any user needs morning/evening reminder."""
    from datetime import datetime
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import User
    from backend.services.daily_reminders import (
        is_working_day, generate_morning_plan, generate_evening_recap, send_reminder,
    )

    sent_today: set[tuple[int, str]] = set()
    current_date = None

    while True:
        await asyncio.sleep(300)  # 5 min interval
        try:
            now = datetime.now(MADRID_TZ)
            today = now.date()
            if current_date != today:
                sent_today.clear()
                current_date = today

            current_time = now.strftime("%H:%M")

            async with async_session() as db:
                result = await db.execute(
                    select(User).where(User.is_active.is_(True))
                )
                users = result.scalars().all()

                for user in users:
                    if _is_qa_user(user):
                        continue

                    if not await is_working_day(db, today, user.region):
                        continue

                    # Morning reminder (window: target to target+5min)
                    if (user.id, "morning") not in sent_today:
                        target = user.morning_reminder_time or "08:00"
                        if _time_in_window(current_time, target):
                            msg = await generate_morning_plan(db, user)
                            if await send_reminder(msg, db=db):
                                sent_today.add((user.id, "morning"))

                    # Evening recap
                    if (user.id, "evening") not in sent_today:
                        target = user.evening_reminder_time or "18:00"
                        if _time_in_window(current_time, target):
                            msg = await generate_evening_recap(db, user, today)
                            if await send_reminder(msg, db=db):
                                sent_today.add((user.id, "evening"))
        except Exception as e:
            logging.error("Daily reminders error: %s", e)


# ── Weekly report via Discord DM (Saturday 08:00 Madrid) ────

async def _weekly_report_loop():
    """Send the weekly report DM every Saturday at 08:00 Europe/Madrid."""
    from datetime import datetime
    from backend.db.database import async_session
    from backend.core.discord_utils import get_bot_token
    from backend.api.routes.discord import _send_discord_dm
    from backend.services.weekly_report_service import generate_weekly_report

    sent_this_week: str | None = None

    while True:
        await asyncio.sleep(300)
        try:
            now = datetime.now(MADRID_TZ)
            week_key = now.strftime("%G-W%V")

            if now.weekday() != 5 or now.hour < 8:
                continue
            if sent_this_week == week_key:
                continue

            owner_id = settings.DISCORD_OWNER_USER_ID
            if not owner_id:
                continue

            async with async_session() as db:
                bot_token = await get_bot_token(db)
                if not bot_token:
                    continue

                report = await generate_weekly_report(db)
                success = await _send_discord_dm(bot_token, owner_id, report)
                if success:
                    sent_this_week = week_key
                    logging.info("Weekly report DM sent for %s", week_key)
                else:
                    logging.warning("Weekly report DM failed for %s", week_key)

        except Exception as e:
            logging.error("Weekly report loop error: %s", e)


# ── Google Calendar sync + meeting alerts ───────────────────

async def _calendar_sync_loop():
    """Sync Google Calendar events every 15 minutes."""
    from datetime import datetime
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import User
    from backend.api.routes.google_calendar import sync_user_events

    while True:
        await asyncio.sleep(900)  # 15 min
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(User).where(
                        User.is_active.is_(True),
                        User.google_calendar_connected.is_(True),
                    )
                )
                users = result.scalars().all()
                for user in users:
                    if _is_qa_user(user):
                        continue
                    try:
                        count = await sync_user_events(db, user)
                        if count:
                            logging.debug("Calendar sync: %d events for user %s", count, user.id)
                    except Exception as e:
                        logging.warning("Calendar sync failed for user %s: %s", user.id, e)
        except Exception as e:
            logging.error("Calendar sync loop error: %s", e)


async def _meeting_alert_loop():
    """Check every minute for upcoming meetings and send alerts."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, and_
    from backend.db.database import async_session
    from backend.db.models import User, Event, EventType
    from backend.api.routes.discord import _send_discord_dm

    sent_alerts: set[int] = set()  # event IDs already alerted

    while True:
        await asyncio.sleep(60)  # every minute
        try:
            now = datetime.now(MADRID_TZ).replace(tzinfo=None)

            async with async_session() as db:
                # Get users with calendar connected
                users_result = await db.execute(
                    select(User).where(
                        User.is_active.is_(True),
                        User.google_calendar_connected.is_(True),
                    )
                )
                users = users_result.scalars().all()

                for user in users:
                    if _is_qa_user(user):
                        continue

                    prefs = (user.preferences or {}).get("meeting_alerts", {})
                    minutes_before = prefs.get("minutes_before", 30)
                    send_discord = prefs.get("discord_dm", True)

                    # Find events starting in [now, now + minutes_before]
                    cutoff = now + timedelta(minutes=minutes_before)
                    events_result = await db.execute(
                        select(Event).where(
                            Event.user_id == user.id,
                            Event.event_type == EventType.meeting,
                            Event.start_time > now,
                            Event.start_time <= cutoff,
                            Event.alert_sent_at.is_(None),
                        )
                    )
                    events = events_result.scalars().all()

                    for event in events:
                        if event.id in sent_alerts:
                            continue

                        mins = int((event.start_time - now).total_seconds() / 60)
                        time_str = event.start_time.strftime("%H:%M")
                        name = user.short_name or user.full_name

                        # Discord DM
                        if send_discord and settings.DISCORD_OWNER_USER_ID:
                            try:
                                from backend.db.models import DiscordSettings
                                from backend.core.security import decrypt_vault_secret

                                ds_result = await db.execute(select(DiscordSettings).limit(1))
                                ds = ds_result.scalar_one_or_none()
                                if ds and ds.bot_token:
                                    bot_token = decrypt_vault_secret(ds.bot_token) if ds.bot_token.startswith("v1:") else ds.bot_token
                                    # Send DM to this user's Discord (use owner_id for now)
                                    msg = f"📅 **Reunión en {mins} min** ({time_str})\n{event.title}"
                                    await _send_discord_dm(bot_token, settings.DISCORD_OWNER_USER_ID, msg)
                            except Exception as e:
                                logging.warning("Meeting alert DM failed for event %s: %s", event.id, e)

                        # Mark as alerted
                        event.alert_sent_at = now
                        sent_alerts.add(event.id)

                    await db.commit()

        except Exception as e:
            logging.error("Meeting alert loop error: %s", e)


# ── Public API ───────────────────────────────────────────────

def start_background_tasks() -> list[asyncio.Task]:
    """Create and return all background asyncio.Tasks.

    The caller (lifespan) is responsible for cancelling them on shutdown.
    """
    tasks: list[asyncio.Task] = []

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

    t = asyncio.create_task(_billing_reminder_loop(), name="billing-check")
    t.add_done_callback(_log_task_error)
    tasks.append(t)

    t = asyncio.create_task(_daily_reminders_loop(), name="daily-reminders")
    t.add_done_callback(_log_task_error)
    tasks.append(t)

    if settings.DISCORD_OWNER_USER_ID:
        t = asyncio.create_task(_weekly_report_loop(), name="weekly-report")
        t.add_done_callback(_log_task_error)
        tasks.append(t)
        logging.info("Weekly report DM enabled (Saturday 08:00 Madrid)")

    if settings.GOOGLE_CLIENT_ID:
        t = asyncio.create_task(_calendar_sync_loop(), name="calendar-sync")
        t.add_done_callback(_log_task_error)
        tasks.append(t)

        t = asyncio.create_task(_meeting_alert_loop(), name="meeting-alerts")
        t.add_done_callback(_log_task_error)
        tasks.append(t)
        logging.info("Google Calendar sync + meeting alerts enabled")

    return tasks
