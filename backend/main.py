from contextlib import asynccontextmanager
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.config import settings
from backend.api.routes import (
    auth, clients, tasks, task_categories, time_entries, users,
    dashboard, discord, billing, projects, communications, pm,
    reports, proposals, growth, invitations, digests, leads, holded,
    income, expenses, expense_categories, taxes, forecasts, advisor, sync, export,
    service_templates, dailys, contacts, activity, notifications, resources,
    billing_events, client_dashboard, engine_integration,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Startup ready. Database schema must be managed via Alembic migrations.")
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
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers including HSTS to every response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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
