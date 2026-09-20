from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.client import ClientCreate
from backend.schemas.contact import ContactCreate


class OnboardingClientCreate(ClientCreate):
    model_config = ConfigDict(extra="forbid")


class OnboardingContactCreate(ContactCreate):
    model_config = ConfigDict(extra="forbid")


class OnboardingProjectCreate(BaseModel):
    """Project fields accepted during client onboarding; client_id is server-owned."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    project_type: str | None = None
    is_recurring: bool = False
    start_date: datetime | None = None
    target_end_date: datetime | None = None
    budget_hours: float | None = None
    weekly_hours_budget: float | None = None
    monthly_hours_budget: float | None = None
    budget_amount: float | None = None
    gsc_url: str | None = None
    ga4_property_id: str | None = None
    pricing_model: str | None = None
    monthly_fee: float | None = None
    unit_price: float | None = None
    unit_label: str | None = None
    scope: str | None = None
    owner_id: int | None = None


class ClientOnboardingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: OnboardingClientCreate
    contacts: list[OnboardingContactCreate] = Field(default_factory=list, max_length=50)
    project: OnboardingProjectCreate | None = None

    @model_validator(mode="after")
    def one_primary_contact(self) -> "ClientOnboardingCreate":
        if sum(contact.is_primary for contact in self.contacts) > 1:
            raise ValueError("Sólo puede haber un contacto principal")
        return self


class ClientOnboardingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["confirmed", "not_committed", "processing"]
    client_id: int | None = None
    contact_ids: list[int] = Field(default_factory=list)
    project_id: int | None = None
    replayed: bool = False
    undo_state: Literal["available", "undone", "unavailable"] = "unavailable"
    change_log_id: int | None = None
