from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from backend.config import settings


def _vault_fernet() -> Fernet:
    """Derive a Fernet key for vault secrets.

    Uses the dedicated VAULT_KEY when configured, otherwise falls back to
    SECRET_KEY (back-compat: existing ciphertext keeps decrypting when VAULT_KEY
    is unset). Set VAULT_KEY so the JWT signing key can be rotated independently
    of the vault encryption key.
    """
    source = settings.VAULT_KEY or settings.SECRET_KEY
    key_bytes = hashlib.sha256(source.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_vault_secret(plaintext: str) -> str:
    """Encrypt a vault secret. Returns a base64-encoded ciphertext prefixed with 'v1:'."""
    if not plaintext:
        return plaintext
    token = _vault_fernet().encrypt(plaintext.encode())
    return "v1:" + token.decode()


def decrypt_vault_secret(ciphertext: str) -> str:
    """Decrypt a vault secret. Legacy plaintext (no 'v1:' prefix) is returned as-is."""
    if not ciphertext or not ciphertext.startswith("v1:"):
        return ciphertext  # Legacy plaintext — return as-is
    try:
        token = ciphertext[3:].encode()
        return _vault_fernet().decrypt(token).decode()
    except (InvalidToken, Exception) as exc:
        raise ValueError("Vault decryption failed") from exc


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require_exp": True},
        )
    except JWTError:
        return None
