from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CommandContext(BaseModel):
    url: str | None = Field(None, max_length=2000)
    title: str | None = Field(None, max_length=500)
    selection: str | None = Field(None, max_length=4000)


class CommandCreate(BaseModel):
    request_key: str = Field(..., min_length=16, max_length=64)
    text: str = Field(..., min_length=1, max_length=4000)
    channel: Literal["app", "extension"] = "app"
    context: CommandContext | None = None


class CommandAnswer(BaseModel):
    field: str = Field(..., min_length=1, max_length=50)
    choice_id: str | None = Field(None, max_length=100)
    value: str | int | None = None


class CommandResolve(BaseModel):
    request_key: str = Field(..., min_length=16, max_length=64)
    revision: int = Field(..., ge=1)
    answers: list[CommandAnswer] = Field(..., min_length=1, max_length=10)


class CommandExecute(BaseModel):
    request_key: str = Field(..., min_length=16, max_length=64)
    revision: int = Field(..., ge=1)


class CommandReceiptResponse(BaseModel):
    id: str
    request_key: str
    raw_text: str
    channel: str
    context: dict[str, Any] | None
    status: str
    intent: dict[str, Any] | None
    prompt: dict[str, Any] | None
    result: dict[str, Any] | None
    change_log_id: int | None
    error: dict[str, str | None] | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


class CommandListResponse(BaseModel):
    items: list[CommandReceiptResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
