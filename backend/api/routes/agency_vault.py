from __future__ import annotations

import logging
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, AgencyAsset, AssetCategory
from backend.schemas.agency_asset import AssetCreate, AssetUpdate, AssetResponse
from backend.api.deps import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vault/assets", tags=["agency-vault"])


@router.get("", response_model=list[AssetResponse])
async def list_assets(
    category: Optional[AssetCategory] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(AgencyAsset).order_by(AgencyAsset.name)
    if category:
        query = query.where(AgencyAsset.category == category)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(
    body: AssetCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        asset = AgencyAsset(**body.model_dump())
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        return asset
    except Exception as e:
        logger.error("vault create_asset error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: int,
    body: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(AgencyAsset).where(AgencyAsset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    await db.commit()
    await db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(AgencyAsset).where(AgencyAsset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    await db.delete(asset)
    await db.commit()
