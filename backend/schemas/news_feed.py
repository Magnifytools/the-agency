from __future__ import annotations

from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class NewsFeedCreate(BaseModel):
    name: str
    url: str
    category: str = "general"
    enabled: bool = True


class NewsFeedUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None


class NewsFeedResponse(BaseModel):
    id: int
    name: str
    url: str
    category: str
    enabled: bool
    last_fetched_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
