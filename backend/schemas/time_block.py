from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TimeBlockCreate(BaseModel):
    model_config = {"extra": "forbid"}
    task_id: int
    # Hora civil de la agencia sin zona ("2026-10-28T10:00").
    starts_at: datetime
    ends_at: datetime


class TimeBlockUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class TimeBlockResponse(BaseModel):
    id: int
    task_id: int
    starts_at: datetime
    ends_at: datetime
    task_title: str
    task_status: str
    task_estimated_minutes: Optional[int] = None
    client_name: Optional[str] = None
