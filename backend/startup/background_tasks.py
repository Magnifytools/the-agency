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

def _fmt_h(minutes: float) -> str:
    """Format minutes as 'Xh' or 'X.Xh'."""
    h = minutes / 60.0
    return f"{int(h)}h" if h == int(h) else f"{h:.1f}h"


async def _weekly_report_loop():
    """Send the weekly report DM every Saturday at 08:00 Europe/Madrid."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, func, and_
    from sqlalchemy.orm import selectinload
    from backend.db.database import async_session
    from backend.db.models import (
        User, TimeEntry, Task, Client, Project, TaskStatus, DiscordSettings,
    )
    from backend.core.security import decrypt_vault_secret

    sent_this_week: str | None = None  # ISO week string to prevent re-sends

    while True:
        await asyncio.sleep(300)  # check every 5 min
        try:
            now = datetime.now(MADRID_TZ)
            week_key = now.strftime("%G-W%V")

            # Saturday (weekday 5), from 08:00 onwards, once per week
            if now.weekday() != 5 or now.hour < 8:
                continue
            if sent_this_week == week_key:
                continue

            # Get bot_token + owner_id
            owner_id = settings.DISCORD_OWNER_USER_ID
            if not owner_id:
                continue

            async with async_session() as db:
                ds_result = await db.execute(select(DiscordSettings).limit(1))
                ds = ds_result.scalar_one_or_none()
                if not ds or not ds.bot_token:
                    continue

                try:
                    bot_token = decrypt_vault_secret(ds.bot_token) if ds.bot_token.startswith("v1:") else ds.bot_token
                except Exception:
                    continue

                # This week range Mon-Fri (report on Saturday covers the week just ended)
                today = now.date()
                ws = today - timedelta(days=today.weekday() + 5)  # This week's Monday
                # Safer: Saturday weekday=5, so Monday = today - 5
                ws = today - timedelta(days=5)
                we_fri = ws + timedelta(days=4)  # Friday
                we_sun = ws + timedelta(days=6)  # Sunday (for DB range)
                start_dt = datetime.combine(ws, datetime.min.time())
                end_dt = datetime.combine(we_sun + timedelta(days=1), datetime.min.time())

                # ── Users ──
                users_result = await db.execute(
                    select(User).where(User.is_active.is_(True)).order_by(User.full_name)
                )
                users = [u for u in users_result.scalars().all() if not _is_qa_user(u)]
                user_map = {u.id: u for u in users}

                # ── Time entries ──
                entries_result = await db.execute(
                    select(TimeEntry).where(
                        TimeEntry.minutes.isnot(None),
                        TimeEntry.date >= start_dt,
                        TimeEntry.date < end_dt,
                    )
                )
                entries = entries_result.scalars().all()

                # ── Tasks completed this week ──
                completed_result = await db.execute(
                    select(Task)
                    .options(selectinload(Task.client))
                    .where(
                        Task.status == TaskStatus.completed,
                        Task.updated_at >= start_dt,
                        Task.updated_at < end_dt,
                    )
                    .order_by(Task.client_id, Task.title)
                )
                completed_tasks = completed_result.scalars().all()

                # ── Tasks still in progress ──
                in_progress_result = await db.execute(
                    select(Task)
                    .options(selectinload(Task.client), selectinload(Task.assigned_user))
                    .where(Task.status == TaskStatus.in_progress)
                    .order_by(Task.client_id, Task.title)
                )
                in_progress_tasks = in_progress_result.scalars().all()

                # ── Tasks pending (not started) ──
                pending_result = await db.execute(
                    select(Task)
                    .options(selectinload(Task.client), selectinload(Task.assigned_user))
                    .where(Task.status == TaskStatus.pending)
                    .order_by(Task.due_date.asc().nulls_last(), Task.title)
                    .limit(15)
                )
                pending_tasks = pending_result.scalars().all()

                # ── Overdue tasks ──
                overdue_result = await db.execute(
                    select(Task)
                    .options(selectinload(Task.client), selectinload(Task.assigned_user))
                    .where(
                        Task.status.notin_([TaskStatus.completed]),
                        Task.due_date < start_dt,
                        Task.due_date.isnot(None),
                    )
                    .order_by(Task.due_date.asc())
                    .limit(15)
                )
                overdue_tasks = overdue_result.scalars().all()

                # ── Aggregate time by user and client ──
                task_ids = {e.task_id for e in entries if e.task_id}
                tasks_map: dict[int, dict] = {}
                if task_ids:
                    task_result = await db.execute(
                        select(Task, Client.name.label("client_name"), Project.monthly_fee)
                        .outerjoin(Client, Task.client_id == Client.id)
                        .outerjoin(Project, Task.project_id == Project.id)
                        .where(Task.id.in_(task_ids))
                    )
                    for row in task_result.all():
                        tasks_map[row[0].id] = {
                            "client_name": row[1] or "Sin cliente",
                            "monthly_fee": row[2] or 0,
                        }

                user_hours: dict[int, float] = {}
                user_tasks_detail: dict[int, dict[str, float]] = {}  # user_id -> {task_title: mins}
                client_hours: dict[str, float] = {}
                client_cost: dict[str, float] = {}

                for entry in entries:
                    mins = entry.minutes or 0
                    uid = entry.user_id
                    if uid not in user_map:
                        continue
                    user_hours[uid] = user_hours.get(uid, 0) + mins

                    client_name = "Sin cliente"
                    if entry.task_id and entry.task_id in tasks_map:
                        client_name = tasks_map[entry.task_id]["client_name"]
                    client_hours[client_name] = client_hours.get(client_name, 0) + mins
                    rate = float(user_map[uid].hourly_rate) if user_map[uid].hourly_rate else float(settings.DEFAULT_HOURLY_RATE)
                    client_cost[client_name] = client_cost.get(client_name, 0) + (mins / 60.0) * rate

                # ════════════════════════════════════════════════
                # BUILD REPORT
                # ════════════════════════════════════════════════
                total_mins = sum(user_hours.values())
                total_capacity_mins = sum((u.weekly_hours or 40) * 60 for u in users)

                lines: list[str] = []

                # Header
                lines.append(f"\U0001f4ca **Repaso Semanal — {ws.strftime('%d/%m')} al {we_fri.strftime('%d/%m/%Y')}**")
                lines.append("")

                # ── Resumen general ──
                if total_capacity_mins:
                    pct = total_mins / total_capacity_mins * 100
                    lines.append(f"\u23f1\ufe0f **Tiempo total:** {_fmt_h(total_mins)} / {_fmt_h(total_capacity_mins)} ({pct:.0f}% capacidad)")
                else:
                    lines.append(f"\u23f1\ufe0f **Tiempo total:** {_fmt_h(total_mins)}")
                lines.append(f"\u2705 **Tareas completadas:** {len(completed_tasks)}")
                lines.append(f"\U0001f504 **En progreso:** {len(in_progress_tasks)}")
                lines.append(f"\U0001f4cb **Pendientes:** {len(pending_tasks)}")
                if overdue_tasks:
                    lines.append(f"\U0001f534 **Vencidas:** {len(overdue_tasks)}")
                lines.append("")

                # ── Tiempo por persona ──
                lines.append("\U0001f465 **Tiempo por persona:**")
                for u in users:
                    mins = user_hours.get(u.id, 0)
                    cap = (u.weekly_hours or 40) * 60
                    name = u.short_name or u.full_name
                    pct = mins / cap * 100 if cap else 0
                    bar = "\U0001f7e9" if pct >= 80 else ("\U0001f7e8" if pct >= 50 else "\U0001f7e5")
                    lines.append(f"  {bar} {name}: {_fmt_h(mins)} / {_fmt_h(cap)} ({pct:.0f}%)")
                lines.append("")

                # ── Tareas completadas (agrupadas por cliente) ──
                if completed_tasks:
                    lines.append("\u2705 **Completado esta semana:**")
                    by_client: dict[str, list[str]] = {}
                    for t in completed_tasks:
                        cn = t.client.name if t.client else "Sin cliente"
                        assignee = ""
                        if t.assigned_to and t.assigned_to in user_map:
                            u = user_map[t.assigned_to]
                            assignee = f" ({u.short_name or u.full_name})"
                        by_client.setdefault(cn, []).append(f"{t.title}{assignee}")
                    for cn, items in sorted(by_client.items()):
                        lines.append(f"  **{cn}:**")
                        for item in items:
                            lines.append(f"    \u2022 {item}")
                    lines.append("")

                # ── En progreso ──
                if in_progress_tasks:
                    lines.append("\U0001f504 **En progreso:**")
                    for t in in_progress_tasks:
                        cn = t.client.name if t.client else "Sin cliente"
                        assignee = ""
                        if t.assigned_user:
                            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}"
                        due = ""
                        if t.due_date:
                            d = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
                            due = f" (vence {d.strftime('%d/%m')})"
                        lines.append(f"  \u2022 [{cn}] {t.title}{assignee}{due}")
                    lines.append("")

                # ── Tiempo por cliente ──
                if client_hours:
                    lines.append("\U0001f3e2 **Tiempo por cliente:**")
                    sorted_clients = sorted(client_hours.items(), key=lambda x: x[1], reverse=True)
                    for name, mins in sorted_clients:
                        cost = client_cost.get(name, 0)
                        pct = (mins / total_mins * 100) if total_mins else 0
                        alert = " \u26a0\ufe0f" if pct > 40 else ""
                        lines.append(f"  \u2022 {name}: {_fmt_h(mins)} ({pct:.0f}%) \u2014 {cost:.0f}\u20ac{alert}")

                    # Zero-activity clients
                    active_clients_result = await db.execute(
                        select(Client.name).where(Client.status == "active")
                    )
                    active_names = {r[0] for r in active_clients_result.all()}
                    inactive = active_names - set(client_hours.keys())
                    if inactive:
                        lines.append(f"  \U0001f4a4 Sin actividad: {', '.join(sorted(inactive))}")
                    lines.append("")

                # ── Vencidas ──
                if overdue_tasks:
                    lines.append(f"\U0001f534 **Tareas vencidas ({len(overdue_tasks)}):**")
                    for t in overdue_tasks[:10]:
                        cn = t.client.name if t.client else "Sin cliente"
                        assignee = ""
                        if t.assigned_user:
                            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}"
                        due = t.due_date.strftime("%d/%m") if t.due_date else "?"
                        lines.append(f"  \u2022 [{cn}] {t.title}{assignee} (venc\u00eda {due})")
                    if len(overdue_tasks) > 10:
                        lines.append(f"  ... y {len(overdue_tasks) - 10} m\u00e1s")
                    lines.append("")

                # ── Pendientes próximos ──
                upcoming = [t for t in pending_tasks if t.due_date]
                if upcoming:
                    lines.append("\U0001f4cb **Pr\u00f3ximas pendientes:**")
                    for t in upcoming[:8]:
                        cn = t.client.name if t.client else "Sin cliente"
                        assignee = ""
                        if t.assigned_user:
                            assignee = f" \u2192 {t.assigned_user.short_name or t.assigned_user.full_name}"
                        d = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
                        lines.append(f"  \u2022 [{cn}] {t.title}{assignee} (vence {d.strftime('%d/%m')})")
                    lines.append("")

                # Footer
                lines.append("\U0001f4aa \u00a1Buen finde!")

                report = "\n".join(lines)

                # Send DM (split into chunks if > 2000 chars)
                from backend.api.routes.discord import _send_discord_dm
                success = await _send_discord_dm(bot_token, owner_id, report)
                if success:
                    sent_this_week = week_key
                    logging.info("Weekly report DM sent for %s", week_key)
                else:
                    logging.warning("Weekly report DM failed for %s", week_key)

        except Exception as e:
            logging.error("Weekly report loop error: %s", e)


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

    return tasks
