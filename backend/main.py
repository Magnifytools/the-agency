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
    my_week,
    automations,
    google_calendar,
    bank_import,
    team_resources,
    cfo,
)

# ── Re-export migration/seed functions so scripts/init_db.py keeps working ──
from backend.startup.migrations import (  # noqa: F401
    _schema_needs_startup_ddl,
    _ensure_columns,
    _ensure_numeric_types,
    _ensure_columns_v2,
    _ensure_columns_v3,
    _ensure_columns_v4,
    _ensure_columns_v5,
    _ensure_columns_v6,
    _ensure_columns_v7,
    _ensure_columns_v8,
    _ensure_columns_v9,
    _ensure_columns_v10,
    _reset_admin_password,
    _seed_national_holidays,
    _cleanup_qa_test_data,
    _ensure_categories,
    _seed_recurring_templates,
    _backfill_module_permissions,
    run_migrations,
)
from backend.startup.background_tasks import (  # noqa: F401
    _generate_recurring_instances,
    start_background_tasks,
)


async def lifespan(app: FastAPI):
    # Run idempotent DDL for new columns on startup
    from sqlalchemy import text
    from backend.db.database import engine
    try:
        async with engine.begin() as conn:
            for sql in [
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,2)",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invoiced_at TIMESTAMPTZ",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS onboarding_intelligence JSONB",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS billing_day INTEGER",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS billing_amount NUMERIC(12,2)",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS next_billing_date DATE",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_billed_date DATE",
                # Evidence file columns (were missing due to sentinel skip)
                "CREATE TABLE IF NOT EXISTS project_evidence (id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), phase_id INTEGER REFERENCES project_phases(id), title VARCHAR(200) NOT NULL, url TEXT, evidence_type VARCHAR(20) DEFAULT 'other', description TEXT, created_by INTEGER REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
                "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)",
                "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_mime_type VARCHAR(100)",
                "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER",
                "ALTER TABLE project_evidence ADD COLUMN IF NOT EXISTS file_content BYTEA",
                # User profile fields for onboarding + reminders
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS short_name VARCHAR(50)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday DATE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR(100)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS morning_reminder_time VARCHAR(5) DEFAULT '08:00'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS evening_reminder_time VARCHAR(5) DEFAULT '18:00'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS slack_template JSONB",
                "CREATE TABLE IF NOT EXISTS team_resources (id SERIAL PRIMARY KEY, title VARCHAR(300) NOT NULL, url VARCHAR(500), description TEXT, category VARCHAR(30) NOT NULL DEFAULT 'tool', tags VARCHAR(500), shared_by INTEGER NOT NULL REFERENCES users(id), is_pinned BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
                "CREATE INDEX IF NOT EXISTS ix_team_resources_category ON team_resources(category)",
                "ALTER TABLE team_resources ADD COLUMN IF NOT EXISTS resource_type VARCHAR(30) DEFAULT 'herramienta'",
                # Google Calendar integration
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_refresh_token VARCHAR(500)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(200)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_calendar_connected BOOLEAN DEFAULT FALSE",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(300) UNIQUE",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual'",
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS alert_sent_at TIMESTAMPTZ",
                # CFO module — costes reales y fees
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS cost_per_hour NUMERIC(10,2) NOT NULL DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS available_hours_month NUMERIC(5,1) NOT NULL DEFAULT 147",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS fee_is_base BOOLEAN NOT NULL DEFAULT TRUE",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS vat_treatment VARCHAR(30) NOT NULL DEFAULT 'domestic_21'",
                # Seed valores CFO (solo primera ejecución, idempotente)
                "UPDATE users SET cost_per_hour = 20.10, available_hours_month = 147 WHERE (full_name ILIKE '%nacho%' OR full_name ILIKE '%ignacio%' OR email ILIKE 'nacho@%') AND cost_per_hour = 0",
                "UPDATE users SET cost_per_hour = 23.52, available_hours_month = 147 WHERE (full_name ILIKE '%david%' OR email ILIKE 'david@%') AND cost_per_hour = 0",
                # Seed monthly_fee (BASE, sin IVA) solo si no está configurado
                "UPDATE projects SET monthly_fee = 2450.00, fee_is_base = TRUE WHERE name ILIKE '%fit%' AND name ILIKE '%seo%' AND (monthly_fee IS NULL OR monthly_fee = 0)",
                "UPDATE projects SET monthly_fee = 2300.00, fee_is_base = TRUE WHERE (name ILIKE '%mind the gap%' OR name ILIKE '%casino%') AND (monthly_fee IS NULL OR monthly_fee = 0)",
                "UPDATE projects SET monthly_fee = 950.00, fee_is_base = TRUE WHERE name ILIKE '%sage%' AND (name ILIKE '%retainer%' OR name ILIKE '%partnership%') AND (monthly_fee IS NULL OR monthly_fee = 0)",
                # VAT treatment según país
                "UPDATE clients SET vat_treatment = 'andorra_exempt' WHERE name ILIKE '%fit%generation%'",
                # Crear proyecto AI-Driven Content bajo Sage si no existe (fee en base, proyecto puntual)
                """
                INSERT INTO projects (name, client_id, status, monthly_fee, fee_is_base, pricing_model, is_recurring, progress_percent, created_at, updated_at)
                SELECT 'AI-Driven Content', c.id, 'active', 3000.00, TRUE, 'project', FALSE, 0, NOW(), NOW()
                FROM clients c
                WHERE c.name ILIKE '%sage%'
                  AND NOT EXISTS (
                    SELECT 1 FROM projects p WHERE p.client_id = c.id AND p.name ILIKE '%ai%driven%content%'
                  )
                LIMIT 1
                """,
            ]:
                await conn.execute(text(sql))
        logging.info("Startup DDL complete.")
    except Exception as e:
        logging.warning("Startup DDL failed (may be expected): %s", e)

    # Cleanup QA/test data and set correct reminder times
    # NOTE: Each SQL uses a SAVEPOINT so that a single failure does not
    # poison the entire PostgreSQL transaction (PG aborts all commands
    # after an error until ROLLBACK, even inside a Python try/except).
    try:
        async with engine.begin() as conn:
            # Define QA user condition
            qa_user_cond = "email LIKE '%example.com' OR full_name LIKE 'QA %' OR full_name LIKE 'AUDIT%'"
            qa_task_cond = "title LIKE 'QA Task%' OR title LIKE 'AUDIT-%'"
            qa_client_cond = "name LIKE 'QA%' OR name LIKE 'AUDIT%' OR name LIKE '__TEST%' OR name LIKE 'QA Client%'"
            for sql in [
                f"UPDATE tasks SET assigned_to = NULL WHERE ({qa_task_cond})",
                f"DELETE FROM time_entries WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM time_entries WHERE task_id IN (SELECT id FROM tasks WHERE {qa_task_cond})",
                f"DELETE FROM task_comments WHERE task_id IN (SELECT id FROM tasks WHERE {qa_task_cond})",
                f"DELETE FROM task_attachments WHERE task_id IN (SELECT id FROM tasks WHERE {qa_task_cond})",
                f"DELETE FROM tasks WHERE {qa_task_cond}",
                f"DELETE FROM daily_updates WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM user_permissions WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM inbox_notes WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM inbox_attachments WHERE uploaded_by IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM alert_settings WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM generated_reports WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"UPDATE proposals SET created_by = NULL WHERE created_by IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"UPDATE audit_logs SET user_id = NULL WHERE user_id IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"UPDATE project_evidence SET created_by = NULL WHERE created_by IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"UPDATE users SET invited_by = NULL WHERE invited_by IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM user_invitations WHERE invited_by IN (SELECT id FROM users WHERE {qa_user_cond})",
                f"DELETE FROM projects WHERE client_id IN (SELECT id FROM clients WHERE {qa_client_cond})",
                f"DELETE FROM clients WHERE {qa_client_cond}",
                f"DELETE FROM users WHERE {qa_user_cond}",
            ]:
                try:
                    await conn.execute(text("SAVEPOINT cleanup_sp"))
                    result = await conn.execute(text(sql))
                    await conn.execute(text("RELEASE SAVEPOINT cleanup_sp"))
                    if result.rowcount > 0:
                        logging.info("QA cleanup: %s -> %d rows", sql[:60], result.rowcount)
                except Exception as sql_err:
                    await conn.execute(text("ROLLBACK TO SAVEPOINT cleanup_sp"))
                    logging.warning("QA cleanup SQL failed (skipping): %s — %s", sql[:60], sql_err)
    except Exception as e:
        logging.warning("QA data cleanup failed (non-fatal): %s", e)

    await _reset_admin_password()

    bg_tasks = start_background_tasks()
    logging.info("Startup ready.")
    yield
    for t in bg_tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="The Agency", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

from backend.config import _is_production

if _is_production():
    _cors_raw = os.environ.get("CORS_ORIGINS", "")
    cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if not cors_origins:
        raise RuntimeError(
            "CORS_ORIGINS must be set in production. "
            "Example: CORS_ORIGINS=https://agency.magnifytools.com"
        )
    if "*" in cors_origins:
        raise RuntimeError("CORS_ORIGINS must not contain '*' in production — this would allow any origin with credentials")
else:
    cors_origins = ["http://localhost:5177"]
    if extra := os.environ.get("CORS_ORIGINS"):
        cors_origins.extend(o.strip() for o in extra.split(",") if o.strip())

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
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://*.supabase.co https://*.railway.app https://discord.com/api wss://*.supabase.co; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
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

# Global error handler — structured JSON for all unhandled exceptions
from backend.api.middleware.error_handler import unhandled_exception_handler
from sqlalchemy.exc import DataError, IntegrityError
app.add_exception_handler(DataError, unhandled_exception_handler)
app.add_exception_handler(IntegrityError, unhandled_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

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
app.include_router(my_week.router)
app.include_router(automations.router)
app.include_router(google_calendar.router)
app.include_router(bank_import.router)
app.include_router(team_resources.router)
app.include_router(cfo.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring and deployment probes."""
    return {"status": "ok", "build": "v6-sprint-digest-timer", "routes": len(app.routes)}


# Serve frontend static files in production
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Return 404 JSON for unknown API routes instead of SPA HTML
        if full_path.startswith("api/") or full_path.startswith("api"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )
        file_path = (_frontend_dist / full_path).resolve()
        # Prevent path traversal: resolved path must stay inside frontend/dist
        if file_path.is_file() and file_path.is_relative_to(_frontend_dist.resolve()):
            return FileResponse(str(file_path))
        return FileResponse(str(_frontend_dist / "index.html"))
