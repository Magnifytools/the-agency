from __future__ import annotations
from typing import Optional

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import PMInsight, User, InsightStatus, AlertSettings
from backend.schemas.insight import InsightResponse, DailyBriefingResponse
from backend.schemas.alert_settings import AlertSettingsResponse, AlertSettingsUpdate
from backend.services.insights import generate_insights, get_daily_briefing
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/pm", tags=["pm"])


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
    _user: User = Depends(get_current_user),
):
    """List all active insights, ordered by priority."""
    query = select(PMInsight)

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


@router.post("/generate-insights", response_model=list[InsightResponse])
async def trigger_generate_insights(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate new insights based on current state.
    This clears old active insights and creates fresh ones.
    """
    # Clear old active insights (they'll be regenerated)
    old_insights = await db.execute(
        select(PMInsight).where(PMInsight.status == InsightStatus.active)
    )
    for old in old_insights.scalars().all():
        await db.delete(old)
    await db.commit()

    # Generate new insights
    new_insights = await generate_insights(db, user_id=current_user.id)

    return [_to_response(i) for i in new_insights]


@router.put("/insights/{insight_id}/dismiss", response_model=InsightResponse)
async def dismiss_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Mark an insight as dismissed."""
    result = await db.execute(select(PMInsight).where(PMInsight.id == insight_id))
    insight = result.scalar_one_or_none()

    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    insight.status = InsightStatus.dismissed
    insight.dismissed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(insight)

    return _to_response(insight)


@router.put("/insights/{insight_id}/act", response_model=InsightResponse)
async def act_on_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Mark an insight as acted upon."""
    result = await db.execute(select(PMInsight).where(PMInsight.id == insight_id))
    insight = result.scalar_one_or_none()

    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    insight.status = InsightStatus.acted
    insight.acted_at = datetime.utcnow()

    await db.commit()
    await db.refresh(insight)

    return _to_response(insight)


@router.get("/daily-briefing", response_model=DailyBriefingResponse)
async def get_briefing(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the daily briefing summary."""
    briefing = await get_daily_briefing(db, user_id=current_user.id)
    return DailyBriefingResponse(**briefing)


@router.post("/briefing/discord")
async def share_briefing_to_discord(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate the daily briefing and share it to Discord via Webhook."""
    from backend.config import settings
    import httpx
    
    if not settings.DISCORD_WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="Discord Webhook URL not configured in settings.")
        
    briefing = await get_daily_briefing(db, user_id=current_user.id)
    
    # Format the message for Discord
    lines = [f"# {briefing['greeting']}"]
    lines.append(f"**Briefing del {briefing['date']}**")
    
    if briefing.get('suggestion'):
        lines.append(f"> 💡 *{briefing['suggestion']}*")
        
    if briefing['priorities']:
        lines.append("\n**📋 Tareas de hoy:**")
        for p in briefing['priorities']:
            client_prefix = f"[{p['client']}] " if p.get('client') else ""
            lines.append(f"- {client_prefix}{p['title']}")
            
    if briefing['alerts']:
        lines.append("\n**🚨 Tareas vencidas:**")
        for a in briefing['alerts']:
            client_prefix = f"[{a['client']}] " if a.get('client') else ""
            lines.append(f"- {client_prefix}{a['title']} ({a['days_overdue']} días)")
            
    if briefing['followups']:
        lines.append("\n**📞 Seguimientos pendientes:**")
        for f in briefing['followups']:
            client_prefix = f"[{f['client']}] " if f.get('client') else ""
            lines.append(f"- {client_prefix}{f['subject']}")
            
    if not briefing['priorities'] and not briefing['alerts'] and not briefing['followups']:
        lines.append("\n*No hay tareas pendientes para hoy.*")
        
    discord_payload = {
        "content": "\n".join(lines),
        "username": "Agency Manager Bot",
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(settings.DISCORD_WEBHOOK_URL, json=discord_payload)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to push to Discord: {str(e)}")
        
    return {"status": "ok", "message": "Briefing shared to Discord."}


@router.get("/insights/count")
async def get_insight_count(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get count of active insights by priority."""
    result = await db.execute(
        select(PMInsight).where(PMInsight.status == InsightStatus.active)
    )
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
    current_user: User = Depends(get_current_user),
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
        await db.refresh(settings)

    return _settings_to_response(settings)


@router.put("/settings/alerts", response_model=AlertSettingsResponse)
async def update_alert_settings(
    data: AlertSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    await db.refresh(settings)

    return _settings_to_response(settings)
