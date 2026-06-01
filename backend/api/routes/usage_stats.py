"""Admin-only usage analytics endpoints.

Reads aggregations from ``audit_logs`` (populated by UsageTrackerMiddleware).
The window defaults to 30 days. Each query is grouped at the route_template
level so paths with ids collapse into a single row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import AuditLog, User
from backend.api.deps import require_admin

router = APIRouter(prefix="/api/admin/usage", tags=["admin-usage"])


def _window(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


@router.get("/top-routes")
async def top_routes(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Most-hit routes in the given window, plus 4xx/5xx error counts."""
    since = _window(days)
    result = await db.execute(
        select(
            AuditLog.route_template,
            AuditLog.method,
            func.count().label("hits"),
            func.avg(AuditLog.duration_ms).label("avg_ms"),
            func.sum(func.case((AuditLog.status_code >= 400, 1), else_=0)).label("errors"),
        )
        .where(
            AuditLog.created_at >= since,
            AuditLog.route_template.isnot(None),
        )
        .group_by(AuditLog.route_template, AuditLog.method)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [
        {
            "route": row.route_template,
            "method": row.method,
            "hits": int(row.hits),
            "avg_ms": int(row.avg_ms) if row.avg_ms is not None else None,
            "errors": int(row.errors or 0),
        }
        for row in result.all()
    ]


@router.get("/by-user")
async def by_user(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Request counts per user in the window."""
    since = _window(days)
    result = await db.execute(
        select(
            AuditLog.user_id,
            User.full_name,
            func.count().label("hits"),
        )
        .join(User, AuditLog.user_id == User.id, isouter=True)
        .where(AuditLog.created_at >= since)
        .group_by(AuditLog.user_id, User.full_name)
        .order_by(func.count().desc())
    )
    return [
        {"user_id": row.user_id, "user_name": row.full_name, "hits": int(row.hits)}
        for row in result.all()
    ]


@router.get("/daily")
async def daily(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Request volume per day in the window."""
    since = _window(days)
    result = await db.execute(
        select(
            func.date(AuditLog.created_at).label("day"),
            func.count().label("hits"),
        )
        .where(AuditLog.created_at >= since)
        .group_by(func.date(AuditLog.created_at))
        .order_by(func.date(AuditLog.created_at))
    )
    return [
        {"day": row.day.isoformat() if row.day else None, "hits": int(row.hits)}
        for row in result.all()
    ]


@router.get("/unused-routes")
async def unused_routes(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Routes registered in the FastAPI app but never hit in the window.

    Compares the live route registry against the routes seen in audit_logs.
    Useful to spot endpoints worth cutting.
    """
    from backend.main import app

    registered: set[tuple[str, str]] = set()
    for r in app.router.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path or not path.startswith("/api"):
            continue
        for m in methods:
            if m == "OPTIONS":
                continue
            registered.add((path, m))

    since = _window(days)
    result = await db.execute(
        select(AuditLog.route_template, AuditLog.method)
        .where(
            AuditLog.created_at >= since,
            AuditLog.route_template.isnot(None),
        )
        .distinct()
    )
    seen = {(row.route_template, row.method) for row in result.all()}
    unused = sorted(registered - seen)
    return [{"route": path, "method": method} for path, method in unused]
