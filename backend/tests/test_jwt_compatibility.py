"""JWT wire compatibility and vault fixtures survive dependency upgrades."""
import base64
import hashlib
import hmac
import json
import time

import pytest

from backend.config import settings
from backend.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_vault_secret,
    encrypt_vault_secret,
)

# Synthetic test material only; never an application credential.
TEST_KEY = "agency-compatibility-test-key-not-for-production"


def _segment(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")


def _signed_token(payload, *, algorithm="HS256", key=TEST_KEY):
    """Independent JWT signer for invalid-claim/algorithm test inputs."""
    message = _segment({"alg": algorithm, "typ": "JWT"}) + b"." + _segment(payload)
    digest = hashlib.sha512 if algorithm == "HS512" else hashlib.sha256
    signature = base64.urlsafe_b64encode(hmac.digest(key.encode(), message, digest)).rstrip(b"=")
    return (message + b"." + signature).decode()


@pytest.fixture(autouse=True)
def synthetic_settings(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", TEST_KEY)
    monkeypatch.setattr(settings, "VAULT_KEY", None)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256")


def test_new_token_preserves_hs256_wire_claims_and_lifetime():
    before = int(time.time())
    token = create_access_token({"sub": "123"})
    header, payload, signature = token.split(".")
    expected = base64.urlsafe_b64encode(
        hmac.digest(TEST_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256)
    ).rstrip(b"=").decode()
    assert hmac.compare_digest(signature, expected)
    assert json.loads(base64.urlsafe_b64decode(header + "=="))["alg"] == "HS256"
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert claims["sub"] == "123"
    assert len(claims["jti"]) == 32
    assert before + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 <= claims["exp"]
    assert claims["exp"] <= int(time.time()) + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert decode_access_token(token) == claims


@pytest.mark.parametrize("claims", [
    {"sub": "123"},  # exp remains mandatory after changing JWT libraries
    {"sub": "123", "exp": 1},
    {"sub": "123", "exp": "invalid"},
    {"sub": 123, "exp": 4102444800},
    {"sub": "123", "exp": 4102444800, "nbf": 4102444700},
    {"sub": "123", "exp": 4102444800, "aud": "other-service"},
    {"sub": "123", "exp": 4102444800, "jti": 123},
])
def test_rejects_invalid_claims(claims):
    assert decode_access_token(_signed_token(claims)) is None


def test_rejects_wrong_signature_and_unconfigured_algorithm():
    claims = {"sub": "123", "exp": 4102444800}
    assert decode_access_token(_signed_token(claims, key="different-key")) is None
    assert decode_access_token(_signed_token(claims, algorithm="HS512")) is None


@pytest.mark.parametrize("token", ["", "not.a.jwt", "..", "eyJhbGciOiJub25lIn0.eyJleHAiOjQxMDI0NDQ4MDB9."])
def test_malformed_or_unsigned_tokens_are_rejected(token):
    assert decode_access_token(token) is None


def test_vault_roundtrip_and_dedicated_key_remain_independent(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_KEY", "synthetic-dedicated-vault-key")
    encrypted = encrypt_vault_secret("synthetic-vault-value")
    monkeypatch.setattr(settings, "SECRET_KEY", "different-jwt-key-with-more-than-32-chars")
    assert decrypt_vault_secret(encrypted) == "synthetic-vault-value"
    assert decrypt_vault_secret("legacy-plaintext-value") == "legacy-plaintext-value"
    with pytest.raises(ValueError, match="Vault decryption failed"):
        decrypt_vault_secret("v1:invalid")


# Generated before the migration with python-jose 3.4.0 and the existing
# Fernet implementation, using TEST_KEY above and synthetic content only.
LEGACY_JOSE_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjQxMDI0NDQ4MDAsImp0aSI6ImxlZ2FjeS1zeW50aGV0aWMtc2Vzc2lvbiJ9.6_KKiTj1mbF1xElYI-9ufCoIo9utOWPAVXHlFwmnGDk'
LEGACY_VAULT_CIPHERTEXT = 'v1:gAAAAABqq4HsTNFvqgBJOwX585XhfAAhgnbkngjSd9N5fVMD8f8GiVDliJFSliwDiEgvM-igCqSFpDabdtqIlApYZC4OqbGt-c5K4KtPUkuy4ZL1WfIjEUM='


def test_accepts_existing_python_jose_session():
    assert decode_access_token(LEGACY_JOSE_TOKEN) == {
        "sub": "123", "exp": 4102444800, "jti": "legacy-synthetic-session",
    }


def test_decrypts_existing_vault_ciphertext_with_secret_key_fallback():
    assert decrypt_vault_secret(LEGACY_VAULT_CIPHERTEXT) == "synthetic-existing-vault-secret"
