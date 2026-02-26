from contextlib import asynccontextmanager
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.db.database import engine
from backend.db.models import Base
from backend.config import settings
from backend.api.routes import (
    auth, clients, tasks, task_categories, time_entries, users,
    dashboard, discord, billing, projects, communications, pm,
    reports, proposals, growth, invitations, digests, leads, holded,
    income, expenses, expense_categories, taxes, forecasts, advisor, sync, export,
    service_templates, dailys, contacts, activity, notifications, resources,
    billing_events, client_dashboard,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SECRET_KEY validation is handled by Settings model_validator in config.py.
    # If we reach here, the key is either non-default or we're in dev mode.
    # TODO(M-03): Migrate DDL below to Alembic. These inline migrations are
    # idempotent (IF NOT EXISTS) but fragile — they run on every startup and
    # cannot be rolled back. Tracked as tech-debt for Sprint 4+.
    async with engine.begin() as conn:
        sa_text = __import__("sqlalchemy").text
        try:
            # Create enum types before create_all (needed for new databases)
            await conn.execute(
                sa_text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'digeststatus') THEN "
                    "CREATE TYPE digeststatus AS ENUM ('draft', 'reviewed', 'sent'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'digesttone') THEN "
                    "CREATE TYPE digesttone AS ENUM ('formal', 'cercano', 'equipo'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadstatus') THEN "
                    "CREATE TYPE leadstatus AS ENUM ('new', 'contacted', 'discovery', 'proposal', 'negotiation', 'won', 'lost'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadsource') THEN "
                    "CREATE TYPE leadsource AS ENUM ('website', 'referral', 'linkedin', 'conference', 'cold_outreach', 'other'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadactivitytype') THEN "
                    "CREATE TYPE leadactivitytype AS ENUM ('note', 'email_sent', 'email_received', 'call', 'meeting', 'proposal_sent', 'status_change', 'followup_set'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'servicetype') THEN "
                    "CREATE TYPE servicetype AS ENUM ('seo_sprint', 'migration', 'market_study', 'consulting_retainer', 'partnership_retainer', 'brand_audit', 'custom'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dailyupdatestatus') THEN "
                    "CREATE TYPE dailyupdatestatus AS ENUM ('draft', 'sent'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resourcetype') THEN "
                    "CREATE TYPE resourcetype AS ENUM ('spreadsheet', 'document', 'email', 'account', 'dashboard', 'other'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'billingcycle') THEN "
                    "CREATE TYPE billingcycle AS ENUM ('monthly', 'bimonthly', 'quarterly', 'annual', 'one_time'); "
                    "END IF; "
                    "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'billingeventtype') THEN "
                    "CREATE TYPE billingeventtype AS ENUM ('invoice_sent', 'payment_received', 'reminder_sent', 'note'); "
                    "END IF; "
                    "END $$;"
                )
            )
            # Create all tables first (safe for new databases)
            await conn.run_sync(Base.metadata.create_all)
            # Then add columns that create_all doesn't add to existing tables
            await conn.execute(
                sa_text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(10) NOT NULL DEFAULT 'medium'")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS holded_contact_id VARCHAR(100)")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS vat_number VARCHAR(50)")
            )
            # Sprint 3: Add 'expired' to proposalstatus enum if it exists
            await conn.execute(
                sa_text(
                    "DO $$ BEGIN "
                    "IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'proposalstatus') THEN "
                    "BEGIN ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'expired'; EXCEPTION WHEN OTHERS THEN NULL; END; "
                    "END IF; "
                    "END $$;"
                )
            )
            # Sprint 3: Make client_id nullable (proposals can start from leads)
            await conn.execute(
                sa_text("ALTER TABLE proposals ALTER COLUMN client_id DROP NOT NULL")
            )
            # Sprint 3: New columns for proposals table
            proposal_cols = [
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES leads(id)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS contact_name VARCHAR(200)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS company_name VARCHAR(200) NOT NULL DEFAULT ''",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS service_type servicetype",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS situation TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS problem TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS cost_of_inaction TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS opportunity TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS approach TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS relevant_cases TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS pricing_options JSONB",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS internal_hours_david NUMERIC(10,1)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS internal_hours_nacho NUMERIC(10,1)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS internal_cost_estimate NUMERIC(10,2)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS estimated_margin_percent NUMERIC(5,2)",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS generated_content JSONB",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS responded_at TIMESTAMP",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS response_notes TEXT",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS valid_until DATE",
                "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS converted_project_id INTEGER REFERENCES projects(id)",
            ]
            for col_sql in proposal_cols:
                await conn.execute(sa_text(col_sql))
            # CRM: client_contacts table + contact_id on communication_logs + weekly_hours on users
            await conn.execute(
                sa_text("ALTER TABLE communication_logs ADD COLUMN IF NOT EXISTS contact_id INTEGER REFERENCES client_contacts(id)")
            )
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_hours FLOAT NOT NULL DEFAULT 40.0")
            )
            # Gantt: add start_date to tasks
            await conn.execute(
                sa_text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMP")
            )
            # Client analytics settings
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS ga4_property_id VARCHAR(50)")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS gsc_url VARCHAR(255)")
            )
            # Client billing settings
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_cycle billingcycle")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_day INTEGER")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS next_invoice_date DATE")
            )
            await conn.execute(
                sa_text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS last_invoiced_date DATE")
            )
            # Enhanced client contacts
            await conn.execute(
                sa_text("ALTER TABLE client_contacts ADD COLUMN IF NOT EXISTS department VARCHAR(100)")
            )
            await conn.execute(
                sa_text("ALTER TABLE client_contacts ADD COLUMN IF NOT EXISTS preferred_channel VARCHAR(50)")
            )
            await conn.execute(
                sa_text("ALTER TABLE client_contacts ADD COLUMN IF NOT EXISTS language VARCHAR(50)")
            )
            await conn.execute(
                sa_text("ALTER TABLE client_contacts ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(300)")
            )
            logging.info("Database schema migrations completed successfully.")
        except Exception as e:
            logging.error(f"Database migration failed: {e}")
            raise

    yield


app = FastAPI(title="The Agency", version="1.0.0", lifespan=lifespan)

cors_origins = ["http://localhost:5177"]
if extra := os.environ.get("CORS_ORIGINS"):
    cors_origins.extend(extra.split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Adds X-Request-ID header to every response for traceability."""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIdMiddleware)

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
