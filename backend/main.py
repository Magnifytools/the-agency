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
    # Schema evolution is an explicit release step. A web replica never seeds,
    # repairs or migrates data and cannot start background work on a partial DB.
    from backend.db.database import engine
    from backend.startup.schema_baseline import check_deployment_ready
    await asyncio.wait_for(check_deployment_ready(engine), timeout=10)
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
    from backend.startup.schema_baseline import check_deployment_ready, EXPECTED_SCHEMA_VERSION
    try:
        await asyncio.wait_for(check_deployment_ready(engine), timeout=5)
    except Exception:
        logging.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready", "revision": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "local"), "schema_revision": EXPECTED_SCHEMA_VERSION}


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
