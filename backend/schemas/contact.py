from __future__ import annotations

from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class ContactCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None
    department: Optional[str] = None
    preferred_channel: Optional[str] = None
    language: Optional[str] = None
    linkedin_url: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None
    department: Optional[str] = None
    preferred_channel: Optional[str] = None
    language: Optional[str] = None
    linkedin_url: Optional[str] = None


class ContactResponse(BaseModel):
    id: int
    client_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    is_primary: bool
    notes: Optional[str] = None
    department: Optional[str] = None
    preferred_channel: Optional[str] = None
    language: Optional[str] = None
    linkedin_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
