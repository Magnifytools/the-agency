from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import ServiceTemplate, ServiceType, User
from backend.schemas.proposal import ServiceTemplateResponse, ServiceTemplateUpdate
from backend.api.deps import require_admin, require_module

router = APIRouter(prefix="/api/service-templates", tags=["service-templates"])


@router.get("", response_model=list[ServiceTemplateResponse])
async def list_service_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("proposals")),
):
    """List all available service templates."""
    result = await db.execute(select(ServiceTemplate).order_by(ServiceTemplate.name))
    return result.scalars().all()


@router.get("/{service_type}", response_model=ServiceTemplateResponse)
async def get_service_template(
    service_type: ServiceType,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("proposals")),
):
    """Get a specific service template by type."""
    result = await db.execute(
        select(ServiceTemplate).where(ServiceTemplate.service_type == service_type)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template no encontrado")
    return template


@router.put("/{service_type}", response_model=ServiceTemplateResponse)
async def update_service_template(
    service_type: ServiceType,
    body: ServiceTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update a service template (admin only)."""
    result = await db.execute(
        select(ServiceTemplate).where(ServiceTemplate.service_type == service_type)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template no encontrado")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "default_phases" and value is not None:
            # Convert PhaseItem list to dicts for JSON storage
            value = [p.model_dump() if hasattr(p, "model_dump") else p for p in value]
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)
    return template
