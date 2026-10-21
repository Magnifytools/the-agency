"""Esquemas del módulo Webs (disponibilidad)."""
from __future__ import annotations

from typing import Optional

import httpx
from pydantic import BaseModel, Field, SecretStr, field_validator

from backend.services.web.safe_http import SSRFError, check_url_syntax
from backend.services.web.slack import is_valid_webhook


def normalize_target_url(value: str) -> str:
    """``ejemplo.com`` → ``https://ejemplo.com/``. Valida la forma (sin red):
    http(s), puertos 80/443, sin credenciales y nunca un host interno."""
    value = (value or "").strip()
    if value and "://" not in value:
        value = f"https://{value}"
    try:
        check_url_syntax(value)
    except SSRFError as exc:
        raise ValueError(str(exc)) from exc
    url = httpx.URL(value)
    path = url.raw_path.decode() or "/"
    port = f":{url.port}" if url.port else ""
    host = url.host.lower().rstrip(".")
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    # Sin fragmento (#…): el servidor nunca lo ve.
    return f"{url.scheme}://{host}{port}{path}"


class UptimeTargetCreate(BaseModel):
    url: str = Field(max_length=500)
    label: Optional[str] = Field(None, max_length=120)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return normalize_target_url(value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class UptimeTargetUpdate(BaseModel):
    url: Optional[str] = Field(None, max_length=500)
    label: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def _url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_target_url(value) if value is not None else None

    @field_validator("label")
    @classmethod
    def _label(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class SlackSettingsUpdate(BaseModel):
    """``webhook_url`` omitido = se conserva el que hay; nunca vuelve en la respuesta."""
    webhook_url: Optional[SecretStr] = None
    channel_hint: Optional[str] = Field(None, max_length=100)
    enabled: bool = True
    downtime_to_slack: bool = True
    user_agent: Optional[str] = Field(None, max_length=300)

    @field_validator("webhook_url")
    @classmethod
    def _webhook(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not is_valid_webhook(raw):
            raise ValueError("Pega un webhook de Slack (https://hooks.slack.com/services/…)")
        return SecretStr(raw)

    @field_validator("channel_hint", "user_agent")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class SlackSettingsResponse(BaseModel):
    configured: bool
    enabled: bool
    active: bool
    revoked_at: Optional[str]
    channel_hint: Optional[str]
    downtime_to_slack: bool
    user_agent: Optional[str]
    updated_at: Optional[str]
