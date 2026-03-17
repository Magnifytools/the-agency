from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, AgencyAsset, AssetCategory
from backend.schemas.agency_asset import AssetCreate, AssetUpdate, AssetResponse
from backend.api.deps import get_current_user, require_admin
from backend.core.security import encrypt_vault_secret, decrypt_vault_secret
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(prefix="/api/vault/assets", tags=["agency-vault"])


def _safe_response(asset: AgencyAsset) -> dict:
    """Build response dict without exposing password."""
    data = {c.name: getattr(asset, c.name) for c in asset.__table__.columns}
    data["has_password"] = bool(asset.password)
    data.pop("password", None)
    return data


@router.get("", response_model=list[AssetResponse])
async def list_assets(
    category: Optional[AssetCategory] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = select(AgencyAsset).order_by(AgencyAsset.name)
    if category:
        query = query.where(AgencyAsset.category == category)
    result = await db.execute(query)
    return [_safe_response(a) for a in result.scalars().all()]


@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(
    body: AssetCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    data = body.model_dump()
    if data.get("password"):
        data["password"] = encrypt_vault_secret(data["password"])
    asset = AgencyAsset(**data)
    db.add(asset)
    await db.commit()
    await safe_refresh(db, asset, log_context="agency_vault")
    return _safe_response(asset)


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

    _UPDATABLE_ASSET_FIELDS = {
        "name", "value", "provider", "url", "notes", "associated_domain",
        "registrar", "expiry_date", "auto_renew", "dns_provider",
        "hosting_type", "tool_category", "monthly_cost", "username",
        "password", "is_active", "subscription_type", "purpose",
    }
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field not in _UPDATABLE_ASSET_FIELDS:
            continue
        if field == "password" and value:
            value = encrypt_vault_secret(value)
        setattr(asset, field, value)
    await db.commit()
    await safe_refresh(db, asset, log_context="agency_vault")
    return _safe_response(asset)


@router.get("/{asset_id}/password")
async def get_asset_password(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return the decrypted password for a single asset. Requires admin."""
    result = await db.execute(
        select(AgencyAsset).where(AgencyAsset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not asset.password:
        return {"password": None}
    return {"password": decrypt_vault_secret(asset.password)}


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
