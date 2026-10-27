"""Accesos compartidos. El secreto sólo entra (SecretStr) y sólo sale por /reveal."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CredentialCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    username: Optional[str] = Field(None, max_length=255)
    # Sin restricciones de Pydantic a propósito: un 422 de validación devuelve el
    # valor recibido en "input". La longitud se comprueba en la ruta.
    secret: SecretStr
    # Clave del autenticador (2FA): suelta o enlace otpauth://. Opcional.
    totp: Optional[SecretStr] = None
    notes: Optional[str] = Field(None, max_length=5000)
    client_id: Optional[int] = None
    shared_user_ids: list[int] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede estar vacío")
        return value

    @field_validator("url", "username", "notes")
    @classmethod
    def _optional(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value)


class CredentialUpdate(BaseModel):
    """Campos a cambiar. ``secret`` sólo si se rota la contraseña; ``client_id``
    a ``null`` lo desvincula (se distingue de "no enviado" con model_fields_set)."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    username: Optional[str] = Field(None, max_length=255)
    secret: Optional[SecretStr] = None
    # Enviada: se cambia; enviada vacía o null: se quita el 2FA. Sin enviar: igual.
    totp: Optional[SecretStr] = None
    notes: Optional[str] = Field(None, max_length=5000)
    client_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede estar vacío")
        return value

    @field_validator("url", "username", "notes")
    @classmethod
    def _optional(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value)


ImportSource = Literal["1password", "bitwarden", "chrome", "csv"]
MAX_IMPORT_ITEMS = 500


class CredentialImportItem(BaseModel):
    """Una fila ya leída del CSV en el navegador. Mismos límites que el alta;
    la longitud del secreto y la clave 2FA se comprueban en la ruta (un 422 de
    Pydantic devolvería el valor recibido)."""
    name: str = Field(..., min_length=1, max_length=200)
    url: Optional[str] = Field(None, max_length=500)
    username: Optional[str] = Field(None, max_length=255)
    secret: SecretStr
    totp: Optional[SecretStr] = None
    notes: Optional[str] = Field(None, max_length=5000)
    client_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre no puede estar vacío")
        return value

    @field_validator("url", "username", "notes")
    @classmethod
    def _optional(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value)


class CredentialImport(BaseModel):
    source: ImportSource
    items: list[CredentialImportItem] = Field(..., min_length=1, max_length=MAX_IMPORT_ITEMS)
    shared_user_ids: list[int] = Field(default_factory=list)


class CredentialImportResult(BaseModel):
    created: int


class CredentialTotpResponse(BaseModel):
    code: str
    next_code: str
    remaining: int
    period: int
    digits: int


class CredentialSharesUpdate(BaseModel):
    user_ids: list[int]


class CredentialRevealRequest(BaseModel):
    purpose: Literal["reveal", "copy"] = "reveal"


class SharedUser(BaseModel):
    id: int
    full_name: str


class CredentialResponse(BaseModel):
    """Lo que ve quien tiene acceso. Nunca lleva el secreto."""
    id: int
    name: str
    url: Optional[str]
    username: Optional[str]
    notes: Optional[str]
    client_id: Optional[int]
    client_name: Optional[str]
    created_by: Optional[int]
    created_by_name: Optional[str]
    updated_at: datetime
    can_manage: bool
    # Si tiene clave 2FA guardada (el código se pide aparte, con /totp).
    has_totp: bool
    # Sólo para quien puede gestionarlo; al resto, vacío.
    shared_with: list[SharedUser]


class CredentialRevealResponse(BaseModel):
    secret: str


class CredentialLogEntry(BaseModel):
    id: int
    action: str
    user_id: Optional[int]
    user_name: Optional[str]
    detail: Optional[str]
    at: datetime
