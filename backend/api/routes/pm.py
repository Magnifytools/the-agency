from __future__ import annotations
from datetime import date
import logging
from typing import Literal, Optional

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import PMInsight, User, InsightStatus, InsightType, AlertSettings
from backend.core.modules import is_enabled
from backend.schemas.insight import InsightResponse, DailyBriefingResponse
from backend.schemas.alert_settings import AlertSettingsResponse, AlertSettingsUpdate
from backend.services.insights import get_daily_briefing
from backend.schemas.delivery import ManualDeliveryReceipt, ManualSendRequest
from backend.services.manual_communications import enqueue_request, format_briefing
from backend.services.temporal import business_today

from backend.api.deps import get_current_user, require_module
from backend.core.rate_limiter import ai_limiter
from backend.db.models import UserRole
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/pm", tags=["pm"])
logger = logging.getLogger(__name__)


def _can_read_module(user: User, module: str) -> bool:
    if user.role == UserRole.admin:
        return True
    return any(p.module == module and p.can_read for p in (user.permissions or []))


def _can_read_financial_insights(user: User) -> bool:
    return (
        is_enabled("finance")
        and is_enabled("billing")
        and _can_read_module(user, "finance_income")
    )


def _sensitive_insight_clause():
    """Rows that may contain finance under current or legacy provenance.

    Before ``financial`` existed, both grouped task debt and overdue income
    used ``overdue`` without a task id. They cannot be separated safely now,
    so access is intentionally conservative. Legacy generic suggestions may
    also have been generated from those amounts; new suggestions use the
    explicit ``operational_suggestion`` type.
    """
    return or_(
        PMInsight.insight_type == InsightType.financial,
        PMInsight.insight_type == InsightType.suggestion,
        and_(
            PMInsight.insight_type == InsightType.overdue,
            PMInsight.task_id.is_(None),
        ),
    )


def _is_sensitive_insight(insight: PMInsight) -> bool:
    return (
        insight.insight_type in {InsightType.financial, InsightType.suggestion}
        or (insight.insight_type == InsightType.overdue and insight.task_id is None)
    )


def _to_response(insight: PMInsight) -> InsightResponse:
    return InsightResponse(
        id=insight.id,
        insight_type=insight.insight_type.value,
        priority=insight.priority.value,
        title=insight.title,
        description=insight.description,
        suggested_action=insight.suggested_action,
        status=insight.status.value,
        dismissed_at=insight.dismissed_at,
        acted_at=insight.acted_at,
        generated_at=insight.generated_at,
        expires_at=insight.expires_at,
        user_id=insight.user_id,
        client_id=insight.client_id,
        project_id=insight.project_id,
        task_id=insight.task_id,
        client_name=insight.client.name if insight.client else None,
        project_name=insight.project.name if insight.project else None,
        task_title=insight.task.title if insight.task else None,
        created_at=insight.created_at,
        updated_at=insight.updated_at,
    )


@router.get("/insights", response_model=list[InsightResponse])
async def list_insights(
    status_filter: Optional[str] = None,
    priority: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm")),
):
    """List active insights, scoped to current user (admin sees all).

    Filters out insights whose expires_at has passed — services/insights.py
    sets a relevant TTL on each insight (1-7 days depending on type) and
    expired ones lose their value as suggestions. The row is left in place;
    Historical rows are preserved; the old generator is retired.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    query = select(PMInsight).options(
        selectinload(PMInsight.client),
        selectinload(PMInsight.project),
        selectinload(PMInsight.task),
    ).where(or_(PMInsight.expires_at.is_(None), PMInsight.expires_at > now))

    # F-04: isolate by user_id for non-admin
    if current_user.role != UserRole.admin:
        query = query.where(PMInsight.user_id == current_user.id)
    if not _can_read_financial_insights(current_user):
        query = query.where(~_sensitive_insight_clause())

    if status_filter:
        query = query.where(PMInsight.status == status_filter)
    else:
        # Default to active only
        query = query.where(PMInsight.status == InsightStatus.active)

    if priority:
        query = query.where(PMInsight.priority == priority)

    # Order by priority (high first) then by generated_at
    query = query.order_by(
        PMInsight.priority.asc(),  # high=0, medium=1, low=2 in enum order
        PMInsight.generated_at.desc()
    )

    result = await db.execute(query)
    return [_to_response(i) for i in result.scalars().all()]


@router.post("/generate-insights", status_code=status.HTTP_410_GONE)
async def trigger_generate_insights(
    _current_user: User = Depends(require_module("pm", write=True)),
):
    """Retired writer retained only to give old clients an actionable response."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="La generación de insights se ha retirado. Usa /incidents.",
    )


@router.put("/insights/{insight_id}/dismiss", response_model=InsightResponse)
async def dismiss_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm", write=True)),
):
    """Mark an insight as dismissed."""
    result = await db.execute(select(PMInsight).where(PMInsight.id == insight_id))
    insight = result.scalar_one_or_none()

    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    # F-04: ownership check
    if current_user.role != UserRole.admin and insight.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your insight")
    if _is_sensitive_insight(insight) and not _can_read_financial_insights(current_user):
        raise HTTPException(status_code=403, detail="Sin acceso al origen financiero de este hallazgo")

    insight.status = InsightStatus.dismissed
    insight.dismissed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await safe_refresh(db, insight, log_context="pm")

    return _to_response(insight)


@router.put("/insights/{insight_id}/act", response_model=InsightResponse)
async def act_on_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm", write=True)),
):
    """Mark an insight as acted upon."""
    result = await db.execute(select(PMInsight).where(PMInsight.id == insight_id))
    insight = result.scalar_one_or_none()

    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    # F-04: ownership check
    if current_user.role != UserRole.admin and insight.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your insight")
    if _is_sensitive_insight(insight) and not _can_read_financial_insights(current_user):
        raise HTTPException(status_code=403, detail="Sin acceso al origen financiero de este hallazgo")

    insight.status = InsightStatus.acted
    insight.acted_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await safe_refresh(db, insight, log_context="pm")

    return _to_response(insight)


@router.get("/daily-briefing", response_model=DailyBriefingResponse)
async def get_briefing(
    scope: Literal["mine", "team"] = "mine",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm")),
):
    """Get the daily briefing summary."""
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)
    if scope == "team" and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="La vista de equipo requiere rol administrador")
    briefing = await get_daily_briefing(
        db, user_id=current_user.id, team=scope == "team"
    )
    return DailyBriefingResponse(**briefing, discord_content=format_briefing(briefing))


@router.post("/briefing/discord", response_model=ManualDeliveryReceipt, status_code=202)
async def share_briefing_to_discord(
    scope: Literal["mine", "team"] = "mine",
    body: ManualSendRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm", write=True)),
):
    if scope == "team" and current_user.role != UserRole.admin:
        raise HTTPException(403, "La vista de equipo requiere rol administrador")
    day = body.date if body and body.date else business_today()
    if body and body.content is not None:
        content = body.content
    else:
        # Legacy callers have no reviewed preview: deterministic fallback, no new
        # AI generation on each click. Current UI sends its displayed snapshot.
        briefing = await get_daily_briefing(db, user_id=current_user.id, team=scope == "team", include_ai=False)
        content = format_briefing(briefing)
        day = date.fromisoformat(briefing["date"])
    return await enqueue_request(db, current_user, kind="pm_briefing", scope=scope, period_start=day,
                                 period_end=day, title=f"Briefing del {day.isoformat()}", content=content)


@router.get("/insights/count")
async def get_insight_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm")),
):
    """Get count of active insights by priority."""
    query = select(PMInsight).where(PMInsight.status == InsightStatus.active)
    # F-04: scope to user
    if current_user.role != UserRole.admin:
        query = query.where(PMInsight.user_id == current_user.id)
    if not _can_read_financial_insights(current_user):
        query = query.where(~_sensitive_insight_clause())
    result = await db.execute(query)
    insights = list(result.scalars().all())

    high = sum(1 for i in insights if i.priority.value == "high")
    medium = sum(1 for i in insights if i.priority.value == "medium")
    low = sum(1 for i in insights if i.priority.value == "low")

    return {
        "total": len(insights),
        "high": high,
        "medium": medium,
        "low": low,
    }


def _settings_to_response(settings: AlertSettings) -> AlertSettingsResponse:
    return AlertSettingsResponse(
        id=settings.id,
        user_id=settings.user_id,
        days_without_activity=settings.days_without_activity,
        days_before_deadline=settings.days_before_deadline,
        days_without_contact=settings.days_without_contact,
        max_tasks_per_week=settings.max_tasks_per_week,
        notify_in_app=settings.notify_in_app,
        notify_email=settings.notify_email,
    )


@router.get("/settings/alerts", response_model=AlertSettingsResponse)
async def get_alert_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm")),
):
    """Get alert settings for the current user, creating defaults if needed."""
    result = await db.execute(
        select(AlertSettings).where(AlertSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings for this user
        settings = AlertSettings(user_id=current_user.id)
        db.add(settings)
        await db.commit()
        await safe_refresh(db, settings, log_context="pm")

    return _settings_to_response(settings)


@router.put("/settings/alerts", response_model=AlertSettingsResponse)
async def update_alert_settings(
    data: AlertSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("pm", write=True)),
):
    """Update alert settings for the current user."""
    result = await db.execute(
        select(AlertSettings).where(AlertSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = AlertSettings(user_id=current_user.id)
        db.add(settings)

    # Update only provided fields
    if data.days_without_activity is not None:
        settings.days_without_activity = data.days_without_activity
    if data.days_before_deadline is not None:
        settings.days_before_deadline = data.days_before_deadline
    if data.days_without_contact is not None:
        settings.days_without_contact = data.days_without_contact
    if data.max_tasks_per_week is not None:
        settings.max_tasks_per_week = data.max_tasks_per_week
    if data.notify_in_app is not None:
        settings.notify_in_app = data.notify_in_app
    if data.notify_email is not None:
        settings.notify_email = data.notify_email

    await db.commit()
    await safe_refresh(db, settings, log_context="pm")

    return _settings_to_response(settings)
