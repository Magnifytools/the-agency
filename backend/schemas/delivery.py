from datetime import date as date_type
from typing import Literal
from pydantic import BaseModel, Field


class DigestDeliveryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=50000)


class ManualSendRequest(BaseModel):
    date: date_type | None = None
    content: str | None = Field(default=None, min_length=1, max_length=50000)


class ResendRequest(BaseModel):
    reviewed: Literal[True]
    review_key: str = Field(min_length=16, max_length=80)


class DeliveryReceipt(BaseModel):
    delivery_id: str
    success: bool
    status: str
    message: str
    source_kind: str
    source_id: int
    source_version: str
    source_changed: bool
    content: str
    created_at: str
    sent_at: str | None
    error_code: str | None
    steps: list[dict]
    can_retry: bool
    can_resend: bool
    can_cancel: bool
    worker_enabled: bool
    title: str | None = None
    scope: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    destination_label: str | None = None


class ManualDeliveryReceipt(DeliveryReceipt):
    # Legacy aliases remain truthful while callers adopt the receipt contract.
    ok: bool = False
    date: str | None = None
