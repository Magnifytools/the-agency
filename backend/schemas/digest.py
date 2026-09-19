from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_serializer, model_validator

from backend.db.models import DigestStatus, DigestTone, ExternalDeliveryAction, ReportCadence


def _serialize_utc(dt: Optional[datetime]) -> Optional[str]:
    """Serialize naive UTC datetime as ISO with 'Z' so clients parse it as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Items within sections ---

class DigestItem(BaseModel):
    title: str
    description: str


class DigestSections(BaseModel):
    done: list[DigestItem] = []
    need: list[DigestItem] = []
    next: list[DigestItem] = []
    metrics: list[DigestItem] = []


class DigestContent(BaseModel):
    greeting: str = ""
    date: str = ""
    sections: DigestSections = DigestSections()
    closing: str = ""


# --- API schemas ---

class DigestGenerateRequest(BaseModel):
    client_id: int
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    tone: DigestTone = DigestTone.cercano

    @model_validator(mode="after")
    def validate_period(self):
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Debes indicar period_start y period_end juntos")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end no puede ser anterior a period_start")
        return self


class DigestUpdateRequest(BaseModel):
    content: Optional[DigestContent] = None
    tone: Optional[DigestTone] = None


class DigestStatusUpdate(BaseModel):
    status: DigestStatus


class DigestResponse(BaseModel):
    id: int
    client_id: int
    client_name: Optional[str] = None
    period_start: date
    period_end: date
    status: DigestStatus
    tone: DigestTone
    content: Optional[DigestContent] = None
    raw_context: Optional[dict] = None
    generated_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    created_by: int
    creator_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("generated_at", "edited_at", "created_at", "updated_at")
    def _ser_dt(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc(dt)

    model_config = {"from_attributes": True}


class DigestRenderResponse(BaseModel):
    format: str  # "slack" | "email"
    rendered: str  # The rendered content (text for Slack, HTML for email)


class ReportPolicyUpdate(BaseModel):
    enabled: bool
    cadence: ReportCadence
    responsible_user_id: Optional[int] = None
    revision: int = Field(ge=0)


class ReportPolicyResponse(BaseModel):
    client_id: int
    configured: bool
    enabled: bool = False
    cadence: ReportCadence = ReportCadence.weekly
    responsible_user_id: Optional[int] = None
    responsible_name: Optional[str] = None
    responsible_active: Optional[bool] = None
    responsible_can_prepare: Optional[bool] = None
    revision: int = 0
    updated_at: Optional[datetime] = None

    @field_serializer("updated_at")
    def _ser_updated_at(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc(dt)


class DigestStateSummary(BaseModel):
    latest_digest_id: Optional[int] = None
    latest_status: Optional[DigestStatus] = None
    version_count: int = 0


class InternalDistributionSummary(BaseModel):
    digest_id: Optional[int] = None
    state: Optional[str] = None
    delivery_id: Optional[str] = None
    sent_at: Optional[datetime] = None

    @field_serializer("sent_at")
    def _ser_sent_at(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc(dt)


class ExternalDeliverySummary(BaseModel):
    digest_id: Optional[int] = None
    state: Literal["confirmed", "unconfirmed"] = "unconfirmed"
    actor_name: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    @field_serializer("confirmed_at")
    def _ser_confirmed_at(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc(dt)


class GenerationPreviewItem(BaseModel):
    client_id: int
    client_name: str
    policy_revision: Optional[int] = None
    cadence: Optional[ReportCadence] = None
    responsible_user_id: Optional[int] = None
    responsible_name: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    eligible: bool
    reason: str
    latest_digest_id: Optional[int] = None
    version_count: int = 0
    state: str
    digest: DigestStateSummary
    internal_distribution: InternalDistributionSummary
    external_delivery: ExternalDeliverySummary


class GenerationPreviewResponse(BaseModel):
    as_of: date
    scope: Literal["mine", "team"]
    items: list[GenerationPreviewItem]
    counts: dict[str, int]


class CohortGenerateItem(BaseModel):
    client_id: int
    policy_revision: int = Field(ge=1)
    period_start: date
    period_end: date


class CohortGenerateRequest(BaseModel):
    items: list[CohortGenerateItem] = Field(min_length=1, max_length=50)
    tone: DigestTone = DigestTone.cercano

    @model_validator(mode="after")
    def unique_clients_and_valid_periods(self):
        ids = [item.client_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Cada cliente solo puede aparecer una vez")
        if any(item.period_end < item.period_start for item in self.items):
            raise ValueError("period_end no puede ser anterior a period_start")
        return self


class CohortGenerateResult(BaseModel):
    client_id: int
    outcome: Literal["generated", "skipped", "failed"]
    digest_id: Optional[int] = None
    reason: Optional[str] = None


class CohortGenerateResponse(BaseModel):
    results: list[CohortGenerateResult]


class ExternalDeliveryEventCreate(BaseModel):
    action: ExternalDeliveryAction


class ExternalDeliveryEventResponse(BaseModel):
    id: int
    digest_id: int
    action: ExternalDeliveryAction
    actor_id: int
    actor_name: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_created_at(self, dt: datetime) -> str:
        return _serialize_utc(dt) or ""


class ExternalDeliveryMutationResponse(BaseModel):
    event: ExternalDeliveryEventResponse
    external_delivery: ExternalDeliverySummary
    has_newer_version: bool
    can_record: bool


class ExternalDeliveryEventsResponse(BaseModel):
    events: list[ExternalDeliveryEventResponse]
    external_delivery: ExternalDeliverySummary
    has_newer_version: bool
    can_record: bool


class PolicyResponsibleResponse(BaseModel):
    id: int
    full_name: str
