from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_serializer, model_validator
from backend.services.temporal import utc_isoformat

IncidentState = Literal["active", "snoozed", "resolved", "dismissed"]


class IncidentResponse(BaseModel):
    id: int
    revision: int
    condition_type: str
    state: IncidentState
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str | None
    href: str
    entity_type: str
    entity_key: str
    created_at: datetime
    snoozed_until: datetime | None
    resolved_at: datetime | None
    resolution_reason: str | None
    dismissal_reason: str | None

    @field_serializer("created_at", "snoozed_until", "resolved_at")
    def serialize_instant(self, value):
        return utc_isoformat(value)


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]
    next_cursor: int | None = None


class IncidentDecision(BaseModel):
    revision: int = Field(ge=1)
    action: Literal["snooze", "dismiss", "reactivate"]
    until: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "snooze" and self.until is None:
            raise ValueError("Indica hasta cuándo quieres posponer el aviso")
        if self.action != "snooze" and self.until is not None:
            raise ValueError("La fecha solo corresponde a una posposición")
        self.reason = self.reason.strip() if self.reason else None
        if self.action == "dismiss" and not self.reason:
            raise ValueError("Indica el motivo para descartar el aviso")
        if self.action != "dismiss" and self.reason:
            raise ValueError("El motivo corresponde al descarte")
        return self
