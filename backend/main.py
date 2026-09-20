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
    reports, proposals, growth, invitations, report_policies, digests, leads, holded,
    income, expenses, expense_categories, taxes, forecasts, advisor, sync, export,
    service_templates, dailys, contacts, activity, notifications, incidents, resources, deliveries, communication_schedules,
    changes, commands,
    billing_events, client_dashboard, engine_integration, investments,
    evidence, search, agency_vault, core_updates, balance,
    inbox,
    extension,
    my_week,
    automations,
    google_calendar,
    bank_import,
    cfo,
    usage_stats,
)

# ── Re-export migration/seed functions so scripts/init_db.py keeps working ──
from backend.startup.migrations import (  # noqa: F401
    _schema_needs_startup_ddl,
    _ensure_pg_enums,
    _ensure_enum_values,
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
    # Create PG enum types before any DDL/INSERT that might depend on them.
    # SQLAlchemy ``Enum(PyEnumClass)`` casts inserts to ``::<typename>``, so a
    # missing enum type breaks every INSERT (e.g. vattreatment on clients).
    try:
        await _ensure_pg_enums()
    except Exception as e:
        logging.warning("_ensure_pg_enums failed (may be expected): %s", e)

    # ...y añadir los valores que falten a los tipos que YA existen. Sin esto,
    # un miembro nuevo de un enum ya desplegado (vattreatment en su día,
    # taskstatus.advanced ahora) revienta el primer INSERT en producción.
    try:
        await _ensure_enum_values()
    except Exception as e:
        logging.warning("_ensure_enum_values failed (may be expected): %s", e)

    # Run idempotent DDL for new columns on startup
    from sqlalchemy import text
    from backend.db.database import engine
    try:
        async with engine.begin() as conn:
            for sql in [
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,2)",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invoiced_at TIMESTAMPTZ",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS link_url TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS advanced_at DATE",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
                "CREATE INDEX IF NOT EXISTS ix_tasks_completed_at ON tasks (completed_at)",
                "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_dedupe ON notifications (user_id, dedupe_key)",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS onboarding_intelligence JSONB",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS billing_day INTEGER",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS billing_amount NUMERIC(12,2)",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS next_billing_date DATE",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_billed_date DATE",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS weekly_hours_budget FLOAT",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS monthly_hours_budget FLOAT",
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
                # Timer pausa/reanudación. Estaban en el modelo pero NO aquí, y
                # create_all no añade columnas a tablas que ya existen: cualquier
                # base cuyo time_entries sea anterior a la función devuelve 500 en
                # GET /api/timer/active — el endpoint más consultado de la
                # aplicación y el núcleo del producto. Producción funciona porque
                # se añadieron a mano; una restauración de backup o un entorno
                # nuevo se quedaba sin cronómetro.
                "ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS paused_at TIMESTAMP",
                "ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS accumulated_seconds INTEGER NOT NULL DEFAULT 0",
                # AuditLog as request analytics sink — original schema was
                # entity-audit (action/entity_type/entity_id NOT NULL) but the
                # table was never written to. Relax NOT NULL + add request
                # fields. SAVEPOINTed in this block so an earlier failure
                # can't poison these.
                "ALTER TABLE audit_logs ALTER COLUMN action DROP NOT NULL",
                "ALTER TABLE audit_logs ALTER COLUMN entity_type DROP NOT NULL",
                "ALTER TABLE audit_logs ALTER COLUMN entity_id DROP NOT NULL",
                "ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL",
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS method VARCHAR(10)",
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS route_template VARCHAR(255)",
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS status_code INTEGER",
                "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_route_created ON audit_logs (route_template, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_user_created ON audit_logs (user_id, created_at DESC)",
                # Undo: journal de cambios (backend/services/change_journal.py).
                # La tabla se crea AQUÍ, a mano: el lifespan no pasa por
                # create_all — sólo lo hace init_db — así que una tabla nueva del
                # ORM no aparece sola en producción.
                "CREATE TABLE IF NOT EXISTS change_logs ("
                "id SERIAL PRIMARY KEY, "
                "user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, "
                "entity_type VARCHAR(50) NOT NULL, "
                "entity_id INTEGER, "
                "action VARCHAR(10) NOT NULL, "
                "label VARCHAR(255) NOT NULL, "
                "operations JSONB NOT NULL, "
                "undone_at TIMESTAMP, "
                "undone_by INTEGER REFERENCES users(id) ON DELETE SET NULL, "
                "created_at TIMESTAMP NOT NULL DEFAULT NOW(), "
                "updated_at TIMESTAMP NOT NULL DEFAULT NOW())",
                # El acceso real es siempre el mismo: los últimos N de un usuario.
                "CREATE INDEX IF NOT EXISTS ix_change_logs_user_created ON change_logs (user_id, created_at DESC)",
            ]:
                # Each statement runs in its own SAVEPOINT so a single failure
                # does not abort the whole transaction (PG aborts all subsequent
                # commands until ROLLBACK after any error). Without this, one
                # broken seed UPDATE silently rolls back unrelated migrations
                # and the affected columns never get created.
                try:
                    await conn.execute(text("SAVEPOINT ddl_sp"))
                    await conn.execute(text(sql))
                    await conn.execute(text("RELEASE SAVEPOINT ddl_sp"))
                except Exception as sql_err:
                    await conn.execute(text("ROLLBACK TO SAVEPOINT ddl_sp"))
                    logging.warning("Startup DDL stmt failed (skipping): %s — %s", sql[:80].replace("\n", " "), sql_err)
        logging.info("Startup DDL complete.")
    except Exception as e:
        logging.warning("Startup DDL failed (may be expected): %s", e)

    # Startup evolves schema only. Legacy cleanup/fee seeds and password resets
    # must never run implicitly on deployment or infer business data from names.

    from backend.startup.project_schema import ensure_project_owner_schema
    await ensure_project_owner_schema(engine)
    from backend.startup.delivery_schema import ensure_delivery_schema
    await ensure_delivery_schema(engine)
    from backend.startup.command_schema import ensure_command_schema
    await ensure_command_schema(engine)
    from backend.startup.report_policy_schema import ensure_report_policy_schema
    await ensure_report_policy_schema(engine)
    from backend.startup.incident_schema import ensure_incident_schema
    await ensure_incident_schema(engine)
    from backend.startup.daily_schema import ensure_daily_schema
    await ensure_daily_schema(engine)
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

from backend.api.middleware.usage_tracker import UsageTrackerMiddleware
app.add_middleware(UsageTrackerMiddleware)


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

# ── Registro de routers ───────────────────────────────────────────────────────
# Los módulos ocultos (backend/core/modules.py) NO se registran: sus rutas no
# existen en la aplicación. El código sigue en el repositorio, listo para volver.
# Reactivar: quitar la clave de HIDDEN_MODULES, o AGENCY_HIDDEN_MODULES en Railway.
from backend.core.modules import hidden_modules  # noqa: E402

_HIDDEN = hidden_modules()

# Núcleo: siempre registrado.
_CORE_ROUTERS = [
    auth, clients, tasks, task_categories, time_entries, users, dashboard,
    projects, pm, report_policies, digests, sync, dailys, contacts, activity, notifications, incidents, deliveries, communication_schedules,
    client_dashboard, engine_integration, inbox, extension, google_calendar,
    usage_stats,
    # changes: el Undo del shell. No es una pantalla, es la red de seguridad
    # de todas las demás — se registra siempre.
    changes, commands,
    # search: 0 llamadas, pero es la paleta ⌘K del shell, no una pantalla.
    search,
    # discord: su PANTALLA está oculta (13 visitas), pero la API se queda. El
    # dashboard lee /api/discord/settings para saber si ofrecer "Enviar a
    # Discord" en el Resumen Diario, y ese envío sí se usa (43 veces en 77
    # días, vía /api/dailys/{id}/send-discord). Apagar el router dejaría la
    # app creyendo que Discord no está configurado — el mismo error que en
    # Vigil: deducir el estado de una integración en vez de leerlo.
    discord,
    # my_week: su PANTALLA está oculta (12 visitas), pero el router también
    # sirve /api/my-week/holidays, que es la gestión de festivos de la página
    # de Ajustes — y Ajustes se conserva. Quitar el router dejaría un trozo de
    # una pantalla viva llamando al vacío. Si algún día se borra el módulo de
    # verdad, los festivos hay que sacarlos de aquí primero.
    my_week,
]

# Opcionales: se registran solo si su módulo no está oculto. Un módulo puede
# tener varios routers (finance son ocho, proposals cuatro).
_OPTIONAL_ROUTERS = {
    "finance": [income, expenses, expense_categories, taxes, forecasts,
                advisor, bank_import, balance],
    "holded": [holded],
    "cfo": [cfo],
    "reports": [reports],
    "proposals": [proposals, service_templates, investments],
    "leads": [leads],
    "growth": [growth],
    "automations": [automations],
    "vault": [agency_vault],
    # ("my_week" no está aquí: ver _CORE_ROUTERS — el router sirve los festivos
    #  de Ajustes, que es una pantalla que se conserva.)
    "billing": [billing, billing_events],
    "communications": [communications],
    "resources": [resources],
    "evidence": [evidence],
    "core_updates": [core_updates],
    "invitations": [invitations],
    "export": [export],
}

for _router_module in _CORE_ROUTERS:
    app.include_router(_router_module.router)

for _key, _mods in _OPTIONAL_ROUTERS.items():
    if _key in _HIDDEN:
        continue
    for _router_module in _mods:
        app.include_router(_router_module.router)

if _HIDDEN:
    logging.info(
        "Módulos ocultos (%d): %s", len(_HIDDEN), ", ".join(sorted(_HIDDEN))
    )


@app.get("/api/config")
async def get_app_config():
    """Public presentation contract shared by web and extension clients."""
    return {
        "timezone": settings.AGENCY_TIMEZONE,
        "hidden_modules": sorted(hidden_modules()),
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring and deployment probes."""
    return {"status": "ok", "build": "v6-sprint-digest-timer", "routes": len(app.routes)}


@app.get("/api/ready")
async def readiness_check():
    from backend.db.database import engine
    from backend.startup.readiness import check_database_ready
    try:
        await check_database_ready(engine)
    except Exception:
        logging.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready", "revision": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "local")}


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
