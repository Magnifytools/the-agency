"""Códigos 2FA (TOTP, RFC 6238) de las cuentas guardadas en Accesos.

Lo que hace 1Password con el "código de un solo uso" de una entrada: se guarda
la clave del autenticador (la que da la web al activar el 2FA, suelta o como
enlace ``otpauth://``) y la app calcula el código de cada momento.

La clave se guarda cifrada como un enlace ``otpauth://totp`` normalizado (clave
+ dígitos + periodo + algoritmo) con ``encrypt_vault_secret``, igual que la
contraseña. Sin dependencias: HMAC de la biblioteca estándar.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
DIGITS = (6, 7, 8)
MIN_PERIOD, MAX_PERIOD = 15, 120
# 10 caracteres base32 = 50 bits: lo mínimo que dan las webs. Por debajo suele
# ser que han pegado el código de 6 dígitos en vez de la clave.
MIN_SECRET_CHARS = 10
MAX_INPUT_LENGTH = 2000

_BASE32 = re.compile(r"^[A-Z2-7]+$")


class TotpError(ValueError):
    """La clave no sirve. El mensaje se puede enseñar tal cual (no lleva la clave)."""


@dataclass(frozen=True)
class TotpConfig:
    secret: str  # base32 en mayúsculas, sin relleno
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"

    @property
    def key(self) -> bytes:
        return base64.b32decode(self.secret + "=" * (-len(self.secret) % 8))


def _clean_secret(value: str) -> str:
    secret = re.sub(r"[\s-]", "", value).upper().rstrip("=")
    if len(secret) < MIN_SECRET_CHARS or not _BASE32.match(secret):
        raise TotpError("No es una clave de autenticador válida: copia la clave (letras y números del 2 al 7) "
                        "o el enlace otpauth:// que da la web al activar el 2FA, no el código de 6 dígitos.")
    try:
        base64.b32decode(secret + "=" * (-len(secret) % 8))
    except ValueError:
        raise TotpError("La clave del autenticador está incompleta.") from None
    return secret


def _int_param(params: dict, name: str, default: int) -> int:
    raw = (params.get(name) or [str(default)])[0]
    try:
        return int(raw)
    except ValueError:
        raise TotpError(f"El enlace otpauth:// trae un '{name}' que no es un número.") from None


def parse(raw: str) -> TotpConfig:
    """Una clave suelta (base32, con o sin espacios) o un enlace ``otpauth://totp/...``."""
    value = (raw or "").strip()
    if not value:
        raise TotpError("La clave del autenticador está vacía.")
    if len(value) > MAX_INPUT_LENGTH:
        raise TotpError("La clave del autenticador es demasiado larga.")
    if not value.lower().startswith("otpauth://"):
        return TotpConfig(secret=_clean_secret(value))
    parts = urlsplit(value)
    if parts.netloc.lower() != "totp":
        raise TotpError("Sólo se admiten códigos que cambian con el tiempo (otpauth://totp), no contadores (hotp).")
    params = parse_qs(parts.query)
    secret = (params.get("secret") or [""])[0]
    if not secret:
        raise TotpError("El enlace otpauth:// no trae la clave (secret).")
    algorithm = (params.get("algorithm") or ["SHA1"])[0].upper()
    if algorithm not in ALGORITHMS:
        raise TotpError("El enlace otpauth:// usa un algoritmo que no conocemos (sólo SHA1, SHA256 o SHA512).")
    digits = _int_param(params, "digits", 6)
    if digits not in DIGITS:
        raise TotpError("El código debe tener 6, 7 u 8 dígitos.")
    period = _int_param(params, "period", 30)
    if not MIN_PERIOD <= period <= MAX_PERIOD:
        raise TotpError(f"El código debe cambiar cada {MIN_PERIOD}–{MAX_PERIOD} segundos.")
    return TotpConfig(secret=_clean_secret(secret), digits=digits, period=period, algorithm=algorithm)


def to_uri(config: TotpConfig) -> str:
    """Forma única en la que se guarda (cifrada): sin etiqueta ni emisor."""
    return (f"otpauth://totp/?secret={quote(config.secret)}&digits={config.digits}"
            f"&period={config.period}&algorithm={config.algorithm}")


def code_at(config: TotpConfig, timestamp: float) -> str:
    counter = int(timestamp // config.period)
    digest = hmac.new(config.key, struct.pack(">Q", counter), ALGORITHMS[config.algorithm]).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** config.digits).zfill(config.digits)


def current(config: TotpConfig, now: float | None = None) -> dict:
    """El código de ahora, el siguiente y los segundos que le quedan al de ahora.
    Con el siguiente, quien mira no tiene que volver a pedirlo (ni dejar otra
    fila en el registro) cuando el de ahora caduca."""
    now = time.time() if now is None else now
    remaining = config.period - int(now) % config.period
    return {
        "code": code_at(config, now),
        "next_code": code_at(config, now + config.period),
        "remaining": remaining,
        "period": config.period,
        "digits": config.digits,
    }
