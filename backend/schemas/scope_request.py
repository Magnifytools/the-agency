"""Peticiones fuera de alcance de un cliente."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ScopeDecision = Literal["pending", "absorb", "bill", "swap"]

MAX_MINUTES = 60000


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class _Fields(BaseModel):
    @field_validator("title", mode="before", check_fields=False)
    @classmethod
    def _strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("detail", "decision_note", mode="before", check_fields=False)
    @classmethod
    def _strip_optional(cls, value):
        return _clean_text(value) if isinstance(value, str) else value


class ScopeRequestCreate(_Fields):
    title: str = Field(min_length=1, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=4000)
    estimated_minutes: int = Field(gt=0, le=MAX_MINUTES)
    project_id: Optional[int] = None
    requested_on: Optional[date] = None
    decision: ScopeDecision = "pending"
    decision_note: Optional[str] = Field(default=None, max_length=1000)


class ScopeRequestUpdate(_Fields):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=4000)
    estimated_minutes: Optional[int] = Field(default=None, gt=0, le=MAX_MINUTES)
    project_id: Optional[int] = None
    requested_on: Optional[date] = None
    decision: Optional[ScopeDecision] = None
    decision_note: Optional[str] = Field(default=None, max_length=1000)


class InboxScopeRequestBody(_Fields):
    """Convertir una nota de "Por aclarar" en petición extra."""
    client_id: int
    title: Optional[str] = Field(default=None, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=4000)
    estimated_minutes: int = Field(gt=0, le=MAX_MINUTES)
    project_id: Optional[int] = None
    requested_on: Optional[date] = None


class ScopeRequestResponse(BaseModel):
    id: int
    client_id: int
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    title: str
    detail: Optional[str] = None
    estimated_minutes: int
    requested_on: date
    decision: ScopeDecision
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    decided_by_name: Optional[str] = None
    created_at: datetime
    created_by_name: Optional[str] = None


class ScopeTotals(BaseModel):
    absorbed_minutes: int = 0
    billable_minutes: int = 0
    swapped_minutes: int = 0
    pending_minutes: int = 0
    count: int = 0


class ScopeRequestList(BaseModel):
    month: str
    totals: ScopeTotals
    items: list[ScopeRequestResponse]
