from __future__ import annotations

from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel


class IndustryNewsCreate(BaseModel):
    title: str
    published_date: date
    content: Optional[str] = None
    url: Optional[str] = None


class IndustryNewsUpdate(BaseModel):
    title: Optional[str] = None
    published_date: Optional[date] = None
    content: Optional[str] = None
    url: Optional[str] = None


class IndustryNewsResponse(BaseModel):
    id: int
    title: str
    published_date: date
    content: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
