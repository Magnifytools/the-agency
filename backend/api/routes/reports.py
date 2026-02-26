from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import GeneratedReport, User, UserRole
from backend.schemas.report import ReportRequest, ReportResponse, ReportSection
from backend.services.reports import generate_report
from backend.services.report_narrator import generate_report_narrative
from backend.api.deps import get_current_user, require_module
from backend.core.rate_limiter import ai_limiter

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _to_response(report: GeneratedReport) -> ReportResponse:
    content = json.loads(report.content)
    return ReportResponse(
        id=report.id,
        type=report.report_type.value,
        title=report.title,
        generated_at=report.generated_at.isoformat(),
        period_start=report.period_start.isoformat() if report.period_start else None,
        period_end=report.period_end.isoformat() if report.period_end else None,
        client_name=report.client.name if report.client else None,
        project_name=report.project.name if report.project else None,
        sections=[ReportSection(**s) for s in content.get("sections", [])],
        summary=content.get("summary", ""),
    )


@router.post("/generate", response_model=ReportResponse)
async def create_report(
    request: ReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports", write=True)),
):
    """Generate a new report."""
    try:
        report = await generate_report(
            db,
            report_type=request.type.value,
            user_id=current_user.id,
            client_id=request.client_id,
            project_id=request.project_id,
            period=request.period.value,
        )
        return _to_response(report)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[ReportResponse])
async def list_reports(
    limit: int = 20,
    client_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """List recently generated reports, optionally filtered by client."""
    query = select(GeneratedReport)
    # F-07: members only see their own reports
    if current_user.role != UserRole.admin:
        query = query.where(GeneratedReport.user_id == current_user.id)
    if client_id is not None:
        query = query.where(GeneratedReport.client_id == client_id)
    query = query.order_by(GeneratedReport.generated_at.desc()).limit(limit)
    result = await db.execute(query)
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Get a specific report by ID."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    # F-07: members can only see their own reports
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    return _to_response(report)


@router.post("/{report_id}/ai-narrative")
async def generate_narrative(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports")),
):
    """Generate an AI narrative version of an existing report."""
    ai_limiter.check(current_user.id, max_requests=10, window_seconds=60)

    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    content = json.loads(report.content)
    sections = content.get("sections", [])
    summary = content.get("summary", "")

    try:
        narrative = await generate_report_narrative(
            report_title=report.title,
            sections=sections,
            summary=summary,
            client_name=report.client.name if report.client else None,
            project_name=report.project.name if report.project else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error generando narrativa: {str(e)}")

    return narrative


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("reports", write=True)),
):
    """Delete a report."""
    result = await db.execute(
        select(GeneratedReport).where(GeneratedReport.id == report_id)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    # F-07: members can only delete their own reports
    if current_user.role != UserRole.admin and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your report")

    await db.delete(report)
    await db.commit()

    return {"ok": True}
