from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel
from backend.db.models import ContractType, ClientStatus


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType = ContractType.monthly
    monthly_budget: Optional[float] = None
    status: ClientStatus = ClientStatus.active
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: Optional[ContractType] = None
    monthly_budget: Optional[float] = None
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None


class ClientResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    contract_type: ContractType
    monthly_budget: Optional[float] = None
    status: ClientStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
