from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.db.database import engine
from backend.db.models import Base
from backend.config import settings, DEFAULT_SECRET_KEY
from backend.api.routes import (
    auth, clients, tasks, task_categories, time_entries, users,
    dashboard, discord, billing, projects, communications, pm,
    reports, proposals, growth, invitations, digests, leads, holded,
    income, expenses, expense_categories, taxes, forecasts, advisor, sync, export,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY:
        logging.warning("SECRET_KEY está usando el valor por defecto. Configura SECRET_KEY en .env para producción.")
    async with engine.begin() as conn:
        sa_text = __import__("sqlalchemy").text
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

# Serve frontend static files in production
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        file_path = (_frontend_dist / full_path).resolve()
        # Prevent path traversal: resolved path must stay inside frontend/dist
        if file_path.is_file() and str(file_path).startswith(str(_frontend_dist.resolve())):
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))
