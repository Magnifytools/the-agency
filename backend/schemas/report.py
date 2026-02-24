from __future__ import annotations
from typing import Optional

from pydantic import BaseModel
from enum import Enum


class ReportType(str, Enum):
    client_status = "client_status"
    weekly_summary = "weekly_summary"
    project_status = "project_status"


class ReportPeriod(str, Enum):
    week = "week"
    month = "month"


class ReportRequest(BaseModel):
    type: ReportType
    client_id: Optional[int] = None
    project_id: Optional[int] = None
    period: ReportPeriod = ReportPeriod.month


class ReportSection(BaseModel):
    title: str
    content: str


class ReportResponse(BaseModel):
    id: int
    type: str
    title: str
    generated_at: str
    period_start: Optional[str]
    period_end: Optional[str]
    client_name: Optional[str]
    project_name: Optional[str]
    sections: list[ReportSection]
    summary: str
