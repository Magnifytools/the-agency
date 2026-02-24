from __future__ import annotations
from typing import Optional

from datetime import datetime
from pydantic import BaseModel


class InsightResponse(BaseModel):
    id: int
    insight_type: str
    priority: str
    title: str
    description: str
    suggested_action: Optional[str]
    status: str
    dismissed_at: Optional[datetime]
    acted_at: Optional[datetime]
    generated_at: datetime
    expires_at: Optional[datetime]
    user_id: Optional[int]
    client_id: Optional[int]
    project_id: Optional[int]
    task_id: Optional[int]
    client_name: Optional[str] = None
    project_name: Optional[str] = None
    task_title: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyBriefingResponse(BaseModel):
    date: str
    greeting: str
    priorities: list[dict]
    alerts: list[dict]
    followups: list[dict]
    suggestion: Optional[str]
