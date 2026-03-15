from contextlib import asynccontextmanager
import asyncio
import logging
import os
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from backend.config import settings
from backend.api.routes import (
    auth, clients, tasks, task_categories, time_entries, users,
    dashboard, discord, billing, projects, communications, pm,
    reports, proposals, growth, invitations, digests, leads, holded,
    income, expenses, expense_categories, taxes, forecasts, advisor, sync, export,
    service_templates, dailys, contacts, activity, notifications, resources,
    billing_events, client_dashboard, engine_integration, investments,
    evidence, search, agency_vault, industry_news, core_updates, balance,
    inbox,
    extension,
    assistant,
)


async def _engine_sync_loop():
    from backend.services.engine_sync_service import sync_engine_metrics
    await asyncio.sleep(60)  # initial delay
    while True:
        try:
            await sync_engine_metrics()
        except Exception as e:
            logging.error("Engine sync loop error: %s", e)
        await asyncio.sleep(settings.ENGINE_SYNC_INTERVAL_HOURS * 3600)


async def _holded_sync_loop():
    """Sync Holded contacts, invoices and expenses every 6 hours."""
    from backend.api.routes.holded import sync_contacts, sync_invoices, sync_expenses
    from backend.db.database import async_session

    await asyncio.sleep(300)  # 5 min initial delay to let DB settle
    while True:
        logging.info("Holded auto-sync starting…")
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


async def _ensure_columns():
    """Add columns that were added to models after initial create_all.

    Uses 'preferences' column on users table as a sentinel: if it exists,
    the schema is already up to date and we skip all DDL statements.
    """
    from sqlalchemy import text
    from backend.db.database import engine

    # Fast path: check if schema is already current using a late-addition sentinel column
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'preferences'"
        ))
        if result.fetchone():
            logging.info("Schema sentinel found — skipping _ensure_columns DDL.")
            return

    logging.info("Schema sentinel not found — running _ensure_columns DDL...")
    stmts = [
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_project_id INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_content_count INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_keyword_count INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_avg_position DOUBLE PRECISION",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_clicks_30d INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_impressions_30d INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_metrics_synced_at TIMESTAMPTZ",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS engine_project_id INTEGER",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS business_model VARCHAR(50)",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS aov DOUBLE PRECISION",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS conversion_rate DOUBLE PRECISION",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS ltv DOUBLE PRECISION",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS seo_maturity_level VARCHAR(20)",
        "ALTER TABLE generated_reports ADD COLUMN IF NOT EXISTS audience VARCHAR(20)",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_summary_data JSONB",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS engine_alerts_data JSONB",
        "CREATE TABLE IF NOT EXISTS project_evidence (id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), phase_id INTEGER REFERENCES project_phases(id), title VARCHAR(200) NOT NULL, url TEXT, file_name VARCHAR(255), file_mime_type VARCHAR(100), file_size_bytes INTEGER, file_content BYTEA, evidence_type VARCHAR(20) DEFAULT 'other', description TEXT, created_by INTEGER REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)",
        "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_mime_type VARCHAR(100)",
        "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER",
        "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_content BYTEA",
        "CREATE TABLE IF NOT EXISTS agency_assets (id SERIAL PRIMARY KEY, category VARCHAR(10) NOT NULL, name VARCHAR(200) NOT NULL, value VARCHAR(500), provider VARCHAR(200), url VARCHAR(500), notes TEXT, associated_domain VARCHAR(200), registrar VARCHAR(200), expiry_date DATE, auto_renew BOOLEAN DEFAULT FALSE, dns_provider VARCHAR(200), hosting_type VARCHAR(50), tool_category VARCHAR(100), monthly_cost NUMERIC(10,2), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "CREATE INDEX IF NOT EXISTS ix_agency_assets_category ON agency_assets (category)",
        "CREATE TABLE IF NOT EXISTS industry_news (id SERIAL PRIMARY KEY, title VARCHAR(300) NOT NULL, content TEXT, url VARCHAR(500), published_date DATE NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_timer ON time_entries (user_id) WHERE minutes IS NULL",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_tasks_client_status ON tasks (client_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_project_status ON tasks (project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_time_entries_task_date ON time_entries (task_id, date DESC)",
        "CREATE INDEX IF NOT EXISTS ix_comm_logs_client_occurred ON communication_logs (client_id, occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_projects_client_status ON projects (client_id, status)",
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS context TEXT",
        """CREATE TABLE IF NOT EXISTS client_documents (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL,
    content BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
)""",
        "CREATE INDEX IF NOT EXISTS ix_client_documents_client_id ON client_documents(client_id)",
        "ALTER TABLE agency_assets ADD COLUMN IF NOT EXISTS username VARCHAR(200)",
        "ALTER TABLE agency_assets ADD COLUMN IF NOT EXISTS password VARCHAR(500)",
        "ALTER TABLE agency_assets ADD COLUMN IF NOT EXISTS is_active BOOLEAN",
        "ALTER TABLE agency_assets ADD COLUMN IF NOT EXISTS subscription_type VARCHAR(50)",
        "ALTER TABLE agency_assets ADD COLUMN IF NOT EXISTS purpose VARCHAR(200)",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS due_date DATE",
        """CREATE TABLE IF NOT EXISTS balance_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
        # Sentinel column — MUST remain last ADD COLUMN so the fast-path check above works
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS estimated_close_date DATE",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS probability INTEGER",
        """CREATE TABLE IF NOT EXISTS task_checklists (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    text VARCHAR(500) NOT NULL,
    is_done BOOLEAN NOT NULL DEFAULT FALSE,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
        "CREATE INDEX IF NOT EXISTS ix_task_checklists_task_id ON task_checklists (task_id)",
        "DO $$ BEGIN CREATE TYPE inboxnotestatus AS ENUM ('pending','classified','processed','dismissed'); EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        """CREATE TABLE IF NOT EXISTS inbox_notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    raw_text TEXT NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'dashboard',
    status inboxnotestatus NOT NULL DEFAULT 'pending',
    project_id INTEGER REFERENCES projects(id),
    client_id INTEGER REFERENCES clients(id),
    resolved_as VARCHAR(20),
    resolved_entity_id INTEGER,
    ai_suggestion JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
        "CREATE INDEX IF NOT EXISTS ix_inbox_notes_user_id ON inbox_notes (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_inbox_notes_project_id ON inbox_notes (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_inbox_notes_client_id ON inbox_notes (client_id)",
        "ALTER TABLE tasks ALTER COLUMN client_id DROP NOT NULL",
        """CREATE TABLE IF NOT EXISTS news_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    url VARCHAR(500) NOT NULL,
    category VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                logging.warning("DDL statement failed (may be expected): %s — %s", sql[:80], exc)
    logging.info("_ensure_columns DDL complete.")


async def _ensure_numeric_types():
    """Convert monetary Float columns to NUMERIC for precision.

    Always runs unconditionally so it works on production servers where
    the _ensure_columns sentinel already exists.
    """
    from sqlalchemy import text
    from backend.db.database import engine

    stmts = [
        "ALTER TABLE income ALTER COLUMN amount TYPE NUMERIC(12,2)",
        "ALTER TABLE income ALTER COLUMN vat_amount TYPE NUMERIC(12,2)",
        "ALTER TABLE expenses ALTER COLUMN amount TYPE NUMERIC(12,2)",
        "ALTER TABLE expenses ALTER COLUMN vat_amount TYPE NUMERIC(12,2)",
        "ALTER TABLE invoices ALTER COLUMN amount TYPE NUMERIC(12,2)",
        "ALTER TABLE invoice_items ALTER COLUMN unit_price TYPE NUMERIC(12,2)",
        "ALTER TABLE users ALTER COLUMN hourly_rate TYPE NUMERIC(10,2)",
        "ALTER TABLE clients ALTER COLUMN monthly_budget TYPE NUMERIC(12,2)",
        "ALTER TABLE clients ALTER COLUMN monthly_fee TYPE NUMERIC(12,2)",
        "ALTER TABLE projects ALTER COLUMN budget_amount TYPE NUMERIC(12,2)",
        "ALTER TABLE proposals ALTER COLUMN budget TYPE NUMERIC(12,2)",
        "ALTER TABLE billing_events ALTER COLUMN amount TYPE NUMERIC(12,2)",
        "ALTER TABLE financial_settings ALTER COLUMN tax_reserve TYPE NUMERIC(12,2)",
        "ALTER TABLE financial_settings ALTER COLUMN credit_limit TYPE NUMERIC(12,2)",
        "ALTER TABLE financial_settings ALTER COLUMN credit_used TYPE NUMERIC(12,2)",
        "ALTER TABLE financial_settings ALTER COLUMN cash_start TYPE NUMERIC(12,2)",
        "ALTER TABLE taxes ALTER COLUMN base_amount TYPE NUMERIC(12,2)",
        "ALTER TABLE taxes ALTER COLUMN tax_amount TYPE NUMERIC(12,2)",
        "ALTER TABLE forecasts ALTER COLUMN projected_income TYPE NUMERIC(12,2)",
        "ALTER TABLE forecasts ALTER COLUMN projected_expenses TYPE NUMERIC(12,2)",
        "ALTER TABLE forecasts ALTER COLUMN projected_taxes TYPE NUMERIC(12,2)",
        "ALTER TABLE forecasts ALTER COLUMN projected_profit TYPE NUMERIC(12,2)",
        "ALTER TABLE balance_snapshots ALTER COLUMN amount TYPE NUMERIC(12,2)",
        # Clean up legacy negative test artifacts
        "DELETE FROM expenses WHERE amount < 0",
        # Allow negative tax_amount (IVA a compensar) and negative base_amount (pérdidas)
        "ALTER TABLE taxes DROP CONSTRAINT IF EXISTS ck_tax_base_amount_non_negative",
        "ALTER TABLE taxes DROP CONSTRAINT IF EXISTS ck_tax_tax_amount_non_negative",
        # Support forced password rotation for compromised credentials
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_required BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE task_checklists ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE inbox_notes ADD COLUMN IF NOT EXISTS link_url VARCHAR(500)",
        # Inbox attachments table
        """CREATE TABLE IF NOT EXISTS inbox_attachments (
            id SERIAL PRIMARY KEY,
            note_id INTEGER NOT NULL REFERENCES inbox_notes(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
            size_bytes INTEGER NOT NULL,
            content BYTEA NOT NULL,
            uploaded_by INTEGER REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_inbox_attachments_note_id ON inbox_attachments(note_id)",
        # Notifications table
        """CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            type VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            message TEXT,
            is_read BOOLEAN NOT NULL DEFAULT false,
            link_url VARCHAR(500),
            entity_type VARCHAR(50),
            entity_id INTEGER,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                logging.warning("DDL statement failed (may be expected): %s — %s", sql[:80], exc)
    logging.info("_ensure_numeric_types DDL complete.")


async def _ensure_columns_v2():
    """Phase 1+2 schema additions: task fields, new statuses, comments, attachments.

    Runs unconditionally with idempotent statements.
    """
    from sqlalchemy import text
    from backend.db.database import engine

    stmts = [
        # Phase 1: Task core fields
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_created_by ON tasks (created_by)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_date DATE",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS waiting_for VARCHAR(255)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS follow_up_date DATE",
        # Phase 1: Enum extension (PostgreSQL)
        "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'backlog'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'waiting'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'in_review'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        # Phase 2: Task comments
        """CREATE TABLE IF NOT EXISTS task_comments (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_task_comments_task_id ON task_comments (task_id)",
        # Phase 2: Task attachments
        """CREATE TABLE IF NOT EXISTS task_attachments (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
            size_bytes INTEGER NOT NULL,
            content BYTEA NOT NULL,
            uploaded_by INTEGER REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_task_attachments_task_id ON task_attachments (task_id)",
        # Sprint 4: Holded check in monthly close
        "ALTER TABLE monthly_closes ADD COLUMN IF NOT EXISTS reviewed_holded BOOLEAN NOT NULL DEFAULT false",
        # Sprint 5: Enhanced subtasks
        "ALTER TABLE task_checklists ADD COLUMN IF NOT EXISTS assigned_to INTEGER REFERENCES users(id)",
        "ALTER TABLE task_checklists ADD COLUMN IF NOT EXISTS due_date DATE",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                logging.warning("DDL v2 statement failed (may be expected): %s — %s", sql[:80], exc)
    logging.info("_ensure_columns_v2 DDL complete.")


def _log_task_error(t: asyncio.Task) -> None:
    if not t.cancelled() and (exc := t.exception()):
        logging.error("Background task %s failed: %s", t.get_name(), exc)


async def _cleanup_qa_test_data():
    """One-time cleanup of QA test data created during E2E testing."""
    from sqlalchemy import select, delete, update, or_, exists
    from backend.db.database import async_session
    from backend.db.models import (
        Client, Task, Project, ProjectPhase, ProjectEvidence,
        TimeEntry, Invoice, InvoiceItem, ClientContact, ClientResource,
        BillingEvent, CommunicationLog, WeeklyDigest, PMInsight, GrowthIdea,
        Proposal, Event, Lead, GeneratedReport, Income, HoldedInvoiceCache,
        InboxNote, TaskChecklist,
    )

    async with async_session() as session:
        # --- Part 1: Delete QA-LIVE test clients ---
        result = await session.execute(
            select(Client).where(Client.name.like("QA-LIVE%"))
        )
        qa_clients = result.scalars().all()

        if qa_clients:
            for client in qa_clients:
                client_id = client.id
                project_ids = list((await session.execute(
                    select(Project.id).where(Project.client_id == client_id)
                )).scalars())
                task_ids = list((await session.execute(
                    select(Task.id).where(Task.client_id == client_id)
                )).scalars())
                invoice_ids = list((await session.execute(
                    select(Invoice.id).where(Invoice.client_id == client_id)
                )).scalars())

                # Nullify nullable FKs
                await session.execute(update(Proposal).where(Proposal.client_id == client_id).values(client_id=None))
                if project_ids:
                    await session.execute(update(Proposal).where(Proposal.converted_project_id.in_(project_ids)).values(converted_project_id=None))
                await session.execute(update(Event).where(Event.client_id == client_id).values(client_id=None))
                if project_ids:
                    await session.execute(update(Event).where(Event.project_id.in_(project_ids)).values(project_id=None))
                await session.execute(update(Lead).where(Lead.converted_client_id == client_id).values(converted_client_id=None))
                await session.execute(update(GeneratedReport).where(GeneratedReport.client_id == client_id).values(client_id=None))
                if project_ids:
                    await session.execute(update(GeneratedReport).where(GeneratedReport.project_id.in_(project_ids)).values(project_id=None))
                await session.execute(update(Income).where(Income.client_id == client_id).values(client_id=None))
                await session.execute(update(HoldedInvoiceCache).where(HoldedInvoiceCache.client_id == client_id).values(client_id=None))

                # PMInsight
                pm_conditions = [PMInsight.client_id == client_id]
                if task_ids:
                    pm_conditions.append(PMInsight.task_id.in_(task_ids))
                if project_ids:
                    pm_conditions.append(PMInsight.project_id.in_(project_ids))
                await session.execute(delete(PMInsight).where(or_(*pm_conditions)))

                # GrowthIdea nullify
                if task_ids:
                    await session.execute(update(GrowthIdea).where(GrowthIdea.task_id.in_(task_ids)).values(task_id=None))
                if project_ids:
                    await session.execute(update(GrowthIdea).where(GrowthIdea.project_id.in_(project_ids)).values(project_id=None))

                # Task self-referential
                if task_ids:
                    await session.execute(update(Task).where(Task.depends_on.in_(task_ids)).values(depends_on=None))
                if task_ids:
                    await session.execute(update(InvoiceItem).where(InvoiceItem.task_id.in_(task_ids)).values(task_id=None))

                # Delete children
                if task_ids:
                    await session.execute(delete(TimeEntry).where(TimeEntry.task_id.in_(task_ids)))
                if invoice_ids:
                    await session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids)))
                if project_ids:
                    await session.execute(delete(ProjectEvidence).where(ProjectEvidence.project_id.in_(project_ids)))

                await session.execute(delete(CommunicationLog).where(CommunicationLog.client_id == client_id))
                await session.execute(delete(ClientContact).where(ClientContact.client_id == client_id))
                await session.execute(delete(ClientResource).where(ClientResource.client_id == client_id))
                await session.execute(delete(BillingEvent).where(BillingEvent.client_id == client_id))
                await session.execute(delete(WeeklyDigest).where(WeeklyDigest.client_id == client_id))
                await session.execute(delete(Task).where(Task.client_id == client_id))
                if project_ids:
                    await session.execute(delete(ProjectPhase).where(ProjectPhase.project_id.in_(project_ids)))
                await session.execute(delete(Project).where(Project.client_id == client_id))
                await session.execute(delete(Invoice).where(Invoice.client_id == client_id))
                await session.delete(client)

            logging.info("🧹 Cleaned up %d QA-LIVE test client(s)", len(qa_clients))

        # --- Part 2: Remove duplicate task ---
        dup_result = await session.execute(
            select(Task).where(
                Task.title == "Optimizar web: eliminar formulario DOM, corregir textos y footer"
            ).order_by(Task.id.asc())
        )
        dup_tasks = dup_result.scalars().all()
        if len(dup_tasks) > 1:
            for t in dup_tasks[1:]:
                await session.delete(t)
            logging.info("🧹 Removed %d duplicate task(s)", len(dup_tasks) - 1)

        # --- Part 3: Remove XSS / test inbox notes ---
        xss_result = await session.execute(
            delete(InboxNote).where(
                or_(
                    InboxNote.raw_text.ilike("%<script>%"),
                    InboxNote.raw_text.ilike("%alert(%"),
                    InboxNote.raw_text.ilike("%<img onerror%"),
                    InboxNote.raw_text.ilike("%javascript:%"),
                )
            )
        )
        if xss_result.rowcount:
            logging.info("🧹 Removed %d XSS/test inbox note(s)", xss_result.rowcount)

        # --- Part 4: Remove standalone test tasks ---
        test_tasks_result = await session.execute(
            select(Task).where(Task.title.ilike("%Tarea test%"))
        )
        test_tasks = test_tasks_result.scalars().all()
        if test_tasks:
            test_task_ids = [t.id for t in test_tasks]
            await session.execute(delete(TaskChecklist).where(TaskChecklist.task_id.in_(test_task_ids)))
            await session.execute(delete(TimeEntry).where(TimeEntry.task_id.in_(test_task_ids)))
            await session.execute(update(Task).where(Task.depends_on.in_(test_task_ids)).values(depends_on=None))
            await session.execute(update(GrowthIdea).where(GrowthIdea.task_id.in_(test_task_ids)).values(task_id=None))
            await session.execute(update(InvoiceItem).where(InvoiceItem.task_id.in_(test_task_ids)).values(task_id=None))
            await session.execute(delete(PMInsight).where(PMInsight.task_id.in_(test_task_ids)))
            await session.execute(delete(Task).where(Task.id.in_(test_task_ids)))
            logging.info("🧹 Removed %d test task(s)", len(test_tasks))

        # --- Part 5: Remove orphaned PM insights ---
        # Delete active insights whose referenced task no longer exists
        from sqlalchemy import exists
        orphan_result = await session.execute(
            delete(PMInsight).where(
                PMInsight.task_id.isnot(None),
                ~exists(select(Task.id).where(Task.id == PMInsight.task_id)),
            )
        )
        if orphan_result.rowcount:
            logging.info("🧹 Removed %d orphaned PM insight(s)", orphan_result.rowcount)

        # Also remove insights that mention test data in their text
        stale_result = await session.execute(
            delete(PMInsight).where(
                or_(
                    PMInsight.title.ilike("%Tarea test%"),
                    PMInsight.description.ilike("%Tarea test%"),
                )
            )
        )
        if stale_result.rowcount:
            logging.info("🧹 Removed %d stale PM insight(s) referencing test data", stale_result.rowcount)

        await session.commit()


async def _ensure_categories():
    """Ensure all expected task categories exist (runs at startup)."""
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import TaskCategory

    REQUIRED = [
        {"name": "Interno", "default_minutes": 30},
    ]
    async with async_session() as session:
        created = 0
        for cat in REQUIRED:
            existing = await session.execute(
                select(TaskCategory).where(TaskCategory.name == cat["name"])
            )
            if not existing.scalar_one_or_none():
                session.add(TaskCategory(**cat))
                created += 1
        if created:
            await session.commit()
            logging.info("📂 Created %d missing task categor(ies)", created)


async def _ensure_columns_v3():
    """Phase 3 schema additions: recurring task fields."""
    from sqlalchemy import text
    from backend.db.database import engine

    stmts = [
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_pattern VARCHAR(20)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_day INTEGER",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_end_date DATE",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurring_parent_id INTEGER REFERENCES tasks(id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_recurring_parent_id ON tasks (recurring_parent_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_is_recurring ON tasks (is_recurring)",
        # A3: Allow tasks without client
        "ALTER TABLE tasks ALTER COLUMN client_id DROP NOT NULL",
        # A4: News sources table
        """CREATE TABLE IF NOT EXISTS news_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    url VARCHAR(500) NOT NULL,
    category VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
        # Discord bot token + channel_id for thread support
        "ALTER TABLE discord_settings ADD COLUMN IF NOT EXISTS bot_token VARCHAR(500)",
        "ALTER TABLE discord_settings ADD COLUMN IF NOT EXISTS channel_id VARCHAR(50)",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                logging.warning("DDL v3 statement failed (may be expected): %s — %s", sql[:80], exc)
    logging.info("_ensure_columns_v3 DDL complete.")


async def _ensure_columns_v4():
    """Phase 4 schema additions: tax regime and IRPF withholding fields."""
    from sqlalchemy import text
    from backend.db.database import engine

    stmts = [
        # Income: tax regime + IRPF withholding
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS tax_regime VARCHAR(50) NOT NULL DEFAULT 'standard'",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS irpf_withholding_rate NUMERIC(5,2) NOT NULL DEFAULT 0",
        "ALTER TABLE income ADD COLUMN IF NOT EXISTS irpf_withholding_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
        # Expenses: tax regime + IRPF withholding
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS tax_regime VARCHAR(50) NOT NULL DEFAULT 'standard'",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS irpf_withholding_rate NUMERIC(5,2) NOT NULL DEFAULT 0",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS irpf_withholding_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                logging.warning("DDL v4 statement failed (may be expected): %s — %s", sql[:80], exc)
    logging.info("_ensure_columns_v4 DDL complete.")


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
            logging.info("🔄 Generated %d recurring task instance(s) for %s", created, today)



async def _recurring_midnight_loop():
    """Background loop that generates recurring task instances at midnight."""
    import asyncio
    from datetime import datetime, timedelta

    while True:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        wait_seconds = (tomorrow - now).total_seconds()
        logging.info("🔄 Recurring task loop: next run in %.0f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await _generate_recurring_instances()
        except Exception as exc:
            logging.error("🔄 Recurring task generation failed: %s", exc)


async def _seed_recurring_templates():
    """Create default recurring task templates if they don't exist yet."""
    from sqlalchemy import select
    from backend.db.database import async_session
    from backend.db.models import Task, Client, User, TaskCategory, TaskPriority

    TEMPLATES = [
        {
            "title": "Preparar y enviar update semanal — Sage Sales Management",
            "client_name": "Sage Sales Management",
            "recurrence_pattern": "weekly",
            "recurrence_day": 0,  # Monday
            "priority": TaskPriority.medium,
            "description": "Preparar el update semanal del proyecto. Revisar tareas completadas, estado actual y próximos pasos. Enviar al cliente vía digest.",
        },
        {
            "title": "Preparar y enviar update semanal — Fit Generation",
            "client_name": "Fit Generation",
            "recurrence_pattern": "weekly",
            "recurrence_day": 0,  # Monday
            "priority": TaskPriority.medium,
            "description": "Preparar el update semanal del proyecto. Revisar tareas completadas, estado actual y próximos pasos. Enviar al cliente vía digest.",
        },
        {
            "title": "Generar informe mensual — Sage Sales Management",
            "client_name": "Sage Sales Management",
            "recurrence_pattern": "monthly",
            "recurrence_day": 1,  # Day 1
            "priority": TaskPriority.high,
            "description": "Generar el informe mensual completo del cliente. Incluir métricas SEO, tareas realizadas, evolución y noticias relevantes del sector.",
        },
        {
            "title": "Generar informe mensual — Fit Generation",
            "client_name": "Fit Generation",
            "recurrence_pattern": "monthly",
            "recurrence_day": 1,  # Day 1
            "priority": TaskPriority.high,
            "description": "Generar el informe mensual completo del cliente. Incluir métricas SEO, tareas realizadas, evolución y noticias relevantes del sector.",
        },
    ]

    async with async_session() as session:
        # Find Nacho user
        nacho_result = await session.execute(
            select(User).where(User.full_name.ilike("%nacho%"))
        )
        nacho = nacho_result.scalar_one_or_none()
        nacho_id = nacho.id if nacho else None

        # Find Reporting category
        cat_result = await session.execute(
            select(TaskCategory).where(TaskCategory.name == "Reporting")
        )
        reporting_cat = cat_result.scalar_one_or_none()
        # Create if missing
        if not reporting_cat:
            reporting_cat = TaskCategory(name="Reporting", default_minutes=60)
            session.add(reporting_cat)
            await session.flush()

        created = 0
        for tmpl in TEMPLATES:
            # Check if already exists
            existing = await session.execute(
                select(Task).where(
                    Task.title == tmpl["title"],
                    Task.is_recurring == True,
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Find client
            client_result = await session.execute(
                select(Client).where(Client.name == tmpl["client_name"])
            )
            client = client_result.scalar_one_or_none()
            if not client:
                logging.warning("🔄 Seed: client '%s' not found, skipping template '%s'", tmpl["client_name"], tmpl["title"])
                continue

            new_template = Task(
                title=tmpl["title"],
                description=tmpl["description"],
                client_id=client.id,
                category_id=reporting_cat.id,
                assigned_to=nacho_id,
                priority=tmpl["priority"],
                status="pending",
                is_recurring=True,
                recurrence_pattern=tmpl["recurrence_pattern"],
                recurrence_day=tmpl["recurrence_day"],
            )
            session.add(new_template)
            created += 1

        if created:
            await session.commit()
            logging.info("🔄 Seeded %d recurring task template(s)", created)


async def _backfill_module_permissions():
    """Ensure all non-admin users have default module permissions (pm, digests, etc.)."""
    from sqlalchemy import select, and_
    from backend.db.database import async_session
    from backend.db.models import User, UserPermission, UserRole

    default_modules = ["dashboard", "clients", "tasks", "projects", "timesheet", "pm", "digests"]
    async with async_session() as db:
        users = (await db.execute(select(User).where(User.role != UserRole.admin))).scalars().all()
        added = 0
        for user in users:
            existing = (await db.execute(
                select(UserPermission.module).where(UserPermission.user_id == user.id)
            )).scalars().all()
            existing_set = set(existing)
            for mod in default_modules:
                if mod not in existing_set:
                    db.add(UserPermission(user_id=user.id, module=mod, can_read=True, can_write=True))
                    added += 1
        if added:
            await db.commit()
            logging.info("Backfilled %d module permissions for existing users.", added)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _ensure_columns()
    await _ensure_numeric_types()
    await _ensure_columns_v2()
    await _ensure_columns_v3()
    await _ensure_columns_v4()
    await _cleanup_qa_test_data()
    await _ensure_categories()
    await _seed_recurring_templates()
    await _generate_recurring_instances()
    await _backfill_module_permissions()
    task = None
    if settings.ENGINE_SYNC_ENABLED and settings.ENGINE_API_URL:
        task = asyncio.create_task(_engine_sync_loop(), name="engine-sync")
        task.add_done_callback(_log_task_error)
        logging.info("Engine sync started (interval: %dh)", settings.ENGINE_SYNC_INTERVAL_HOURS)
    holded_task = None
    if settings.HOLDED_API_KEY:
        holded_task = asyncio.create_task(_holded_sync_loop(), name="holded-sync")
        holded_task.add_done_callback(_log_task_error)
        logging.info("Holded auto-sync started (every 6h).")
    recurring_task = asyncio.create_task(_recurring_midnight_loop(), name="recurring-gen")
    recurring_task.add_done_callback(_log_task_error)
    logging.info("Startup ready.")
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if holded_task:
        holded_task.cancel()
        try:
            await holded_task
        except asyncio.CancelledError:
            pass
    recurring_task.cancel()
    try:
        await recurring_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="The Agency", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

cors_origins = ["http://localhost:5177"]
if extra := os.environ.get("CORS_ORIGINS"):
    parsed = [o.strip() for o in extra.split(",") if o.strip()]
    from backend.config import _is_production
    if _is_production() and "*" in parsed:
        raise RuntimeError("CORS_ORIGINS must not contain '*' in production — this would allow any origin with credentials")
    cors_origins.extend(parsed)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every response. HSTS only in production."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if settings.AUTH_COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Adds X-Request-ID header to every response for traceability."""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


class CsrfProtectionMiddleware(BaseHTTPMiddleware):
    """Protect cookie-authenticated mutating requests with double-submit CSRF."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {
        "/api/auth/login",
        "/api/auth/logout",
        "/api/invitations/accept",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        if request.method in self.SAFE_METHODS or not path.startswith("/api"):
            return await call_next(request)
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        auth_cookie = request.cookies.get(settings.AUTH_COOKIE_NAME)

        # Enforce CSRF only for session-cookie auth. Bearer-token API clients are unaffected.
        if auth_cookie and not auth_header:
            csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
            csrf_header = request.headers.get("X-CSRF-Token")
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})

        return await call_next(request)


app.add_middleware(CsrfProtectionMiddleware)


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect HTTP to HTTPS in production (Railway sets X-Forwarded-Proto)."""
    async def dispatch(self, request: Request, call_next):
        if settings.AUTH_COOKIE_SECURE:
            proto = request.headers.get("X-Forwarded-Proto", "https")
            if proto == "http":
                url = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url, status_code=301)
        return await call_next(request)


app.add_middleware(HttpsRedirectMiddleware)

app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(tasks.router)
app.include_router(task_categories.router)
app.include_router(time_entries.router)
app.include_router(users.router)
app.include_router(dashboard.router)
app.include_router(discord.router)
app.include_router(billing.router)
app.include_router(projects.router)
app.include_router(communications.router)
app.include_router(pm.router)
app.include_router(reports.router)
app.include_router(proposals.router)
app.include_router(service_templates.router)
app.include_router(growth.router)
app.include_router(invitations.router)
app.include_router(digests.router)
app.include_router(leads.router)
app.include_router(holded.router)
# Financial routes
app.include_router(income.router)
app.include_router(expenses.router)
app.include_router(expense_categories.router)
app.include_router(taxes.router)
app.include_router(forecasts.router)
app.include_router(advisor.router)
app.include_router(sync.router)
app.include_router(export.router)
app.include_router(dailys.router)
app.include_router(contacts.router)
app.include_router(activity.router)
app.include_router(notifications.router)
app.include_router(resources.router)
app.include_router(billing_events.router)
app.include_router(client_dashboard.router)
app.include_router(engine_integration.router)
app.include_router(investments.router)
app.include_router(evidence.router)
app.include_router(search.router)
app.include_router(agency_vault.router)
app.include_router(industry_news.router)
app.include_router(core_updates.router)
app.include_router(balance.router)
app.include_router(inbox.router)
app.include_router(extension.router)
app.include_router(assistant.router)

# Serve frontend static files in production
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file_path = (_frontend_dist / full_path).resolve()
        # Prevent path traversal: resolved path must stay inside frontend/dist
        if file_path.is_file() and file_path.is_relative_to(_frontend_dist.resolve()):
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))
