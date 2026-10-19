from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class CompanyHolidayCreate(BaseModel):
    date: date
    name: str = Field(..., max_length=100)
    country: str = Field("ES", max_length=5)
    region: Optional[str] = Field(None, max_length=10)
    locality: Optional[str] = Field(None, max_length=100)


class CompanyHolidayResponse(BaseModel):
    id: int
    date: date
    name: str
    country: str
    region: Optional[str] = None
    locality: Optional[str] = None

    model_config = {"from_attributes": True}
