"""Esquemas del módulo Webs (disponibilidad y vigilancia de cambios)."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

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


# ── Vigilancia de cambios (fase 2a) ─────────────────────────────────────────

_MAX_RULES = 30
_MAX_RULE_LEN = 300
Severity = Literal["critical", "warning", "info"]


def _clean_label(value: Optional[str]) -> Optional[str]:
    return value.strip() or None if value else None


def validate_selector(value: str) -> str:
    """Un selector CSS que lxml sabe usar. Vigil ignoraba en silencio uno roto;
    aquí se rechaza al guardar, que es cuando alguien puede corregirlo."""
    from cssselect import GenericTranslator, SelectorError

    value = (value or "").strip()
    if not value or len(value) > _MAX_RULE_LEN:
        raise ValueError("Selector vacío o demasiado largo")
    try:
        GenericTranslator().css_to_xpath(value)
    except SelectorError as exc:
        raise ValueError(f"Selector CSS no válido: {value!r}") from exc
    return value


def validate_regex(value: str) -> str:
    if not value or len(value) > _MAX_RULE_LEN:
        raise ValueError("Expresión vacía o demasiado larga")
    try:
        re.compile(value)
    except re.error as exc:
        raise ValueError(f"Expresión regular no válida: {value!r} ({exc})") from exc
    return value


def _selectors(value: Optional[list[str]]) -> Optional[list[str]]:
    if value is None:
        return None
    if len(value) > _MAX_RULES:
        raise ValueError(f"Como mucho {_MAX_RULES} selectores")
    return list(dict.fromkeys(validate_selector(v) for v in value))


def _regexes(value: Optional[list[str]]) -> Optional[list[str]]:
    if value is None:
        return None
    if len(value) > _MAX_RULES:
        raise ValueError(f"Como mucho {_MAX_RULES} expresiones")
    return list(dict.fromkeys(validate_regex(v) for v in value))


def _content_selector(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    return validate_selector(value)


class WatchFlags(BaseModel):
    watch_seo: bool = True
    watch_content: bool = True
    watch_links: bool = False
    watch_html: bool = False


class WatchCreate(WatchFlags):
    url: str = Field(max_length=500)
    label: Optional[str] = Field(None, max_length=200)
    content_selector: Optional[str] = Field(None, max_length=500)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return normalize_target_url(value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: Optional[str]) -> Optional[str]:
        return _clean_label(value)

    @field_validator("content_selector")
    @classmethod
    def _selector(cls, value: Optional[str]) -> Optional[str]:
        return _content_selector(value)


class WatchUpdate(BaseModel):
    """Lo que no venga no se toca. ``ignore_*: null`` = vuelve a heredar del cliente."""
    label: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None
    muted: Optional[bool] = None
    watch_seo: Optional[bool] = None
    watch_content: Optional[bool] = None
    watch_links: Optional[bool] = None
    watch_html: Optional[bool] = None
    content_selector: Optional[str] = Field(None, max_length=500)
    ignore_selectors: Optional[list[str]] = None
    ignore_regexes: Optional[list[str]] = None

    @field_validator("label")
    @classmethod
    def _label(cls, value: Optional[str]) -> Optional[str]:
        return _clean_label(value)

    @field_validator("content_selector")
    @classmethod
    def _selector(cls, value: Optional[str]) -> Optional[str]:
        return _content_selector(value)

    @field_validator("ignore_selectors")
    @classmethod
    def _ignore(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _selectors(value)

    @field_validator("ignore_regexes")
    @classmethod
    def _regex(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _regexes(value)


class WatchBulkCreate(WatchFlags):
    """Alta en bloque (lista pegada o CSV). Las URLs se validan una a una y el
    recuento dice qué pasó con cada una; no se rechaza el lote entero."""
    urls: list[str] = Field(min_length=1, max_length=5000)
    source: Literal["bulk", "csv"] = "bulk"


class SitemapImport(BaseModel):
    sitemap_url: str = Field(max_length=500)
    include: Optional[str] = Field(None, max_length=300)
    exclude: Optional[str] = Field(None, max_length=300)
    limit: int = Field(200, ge=1, le=500)

    @field_validator("sitemap_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return normalize_target_url(value)

    @field_validator("include", "exclude")
    @classmethod
    def _pattern(cls, value: Optional[str]) -> Optional[str]:
        return validate_regex(value) if value else None


class WatchPreview(BaseModel):
    """Configuración a probar. Lo que no venga se hereda de lo ya guardado."""
    content_selector: Optional[str] = Field(None, max_length=500)
    ignore_selectors: Optional[list[str]] = None
    ignore_regexes: Optional[list[str]] = None

    @field_validator("ignore_selectors")
    @classmethod
    def _ignore(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _selectors(value)

    @field_validator("ignore_regexes")
    @classmethod
    def _regex(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _regexes(value)


class ChangeAck(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class ChangeAckAll(BaseModel):
    """Marcar de golpe lo que se está viendo: sin ``client_id``, todos los
    clientes; sin ``severity``, todas las severidades."""
    client_id: Optional[int] = None
    severity: Optional[Severity] = None


class CaptureSettingsUpdate(BaseModel):
    """Lo que no venga no se toca; ``null`` = vuelve al default del código."""
    default_content_selector: Optional[str] = Field(None, max_length=500)
    default_ignore_selectors: Optional[list[str]] = None
    default_ignore_regexes: Optional[list[str]] = None
    max_concurrency: Optional[int] = Field(None, ge=1, le=12)
    request_timeout_s: Optional[int] = Field(None, ge=5, le=60)
    crawl_delay_ms: Optional[int] = Field(None, ge=0, le=10000)
    digest_min_severity: Optional[Severity] = None

    @field_validator("default_content_selector")
    @classmethod
    def _selector(cls, value: Optional[str]) -> Optional[str]:
        return _content_selector(value)

    @field_validator("default_ignore_selectors")
    @classmethod
    def _ignore(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _selectors(value)

    @field_validator("default_ignore_regexes")
    @classmethod
    def _regex(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _regexes(value)


class ChangesEnabledUpdate(BaseModel):
    enabled: bool


class CalendarSettingsUpdate(BaseModel):
    sweep_weekdays: list[int] = Field(min_length=1, max_length=7)
    sweep_skip_dates: list[str] = Field(default_factory=list, max_length=400)
    sweep_summary_to_slack: bool = True

    @field_validator("sweep_weekdays")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in value):
            raise ValueError("Los días van de 1 (lunes) a 7 (domingo)")
        return sorted(set(value))

    @field_validator("sweep_skip_dates")
    @classmethod
    def _dates(cls, value: list[str]) -> list[str]:
        for item in value:
            try:
                date.fromisoformat(item)
            except ValueError as exc:
                raise ValueError(f"Fecha no válida: {item} (formato AAAA-MM-DD)") from exc
        return sorted(set(value))
