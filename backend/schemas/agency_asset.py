from __future__ import annotations

from typing import Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel
from backend.db.models import AssetCategory


class AssetCreate(BaseModel):
    category: AssetCategory
    name: str
    value: Optional[str] = None
    provider: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    associated_domain: Optional[str] = None
    registrar: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_renew: bool = False
    dns_provider: Optional[str] = None
    hosting_type: Optional[str] = None
    tool_category: Optional[str] = None
    monthly_cost: Optional[Decimal] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    provider: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    associated_domain: Optional[str] = None
    registrar: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_renew: Optional[bool] = None
    dns_provider: Optional[str] = None
    hosting_type: Optional[str] = None
    tool_category: Optional[str] = None
    monthly_cost: Optional[Decimal] = None


class AssetResponse(BaseModel):
    id: int
    category: AssetCategory
    name: str
    value: Optional[str] = None
    provider: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    associated_domain: Optional[str] = None
    registrar: Optional[str] = None
    expiry_date: Optional[date] = None
    auto_renew: bool
    dns_provider: Optional[str] = None
    hosting_type: Optional[str] = None
    tool_category: Optional[str] = None
    monthly_cost: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
