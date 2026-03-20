from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.core.rate_limiter import LoginRateLimiter
from backend.core.security import hash_password


class TestLoginRateLimiter:
    def test_allows_under_limit(self):
        limiter = LoginRateLimiter()
        for _ in range(4):
            limiter.check("test@test.com", max_requests=5, window_seconds=300)

    def test_blocks_over_limit(self):
        limiter = LoginRateLimiter()
        for _ in range(5):
            limiter.check("test@test.com", max_requests=5, window_seconds=300)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("test@test.com", max_requests=5, window_seconds=300)
        assert exc_info.value.status_code == 429

    def test_different_keys_independent(self):
        limiter = LoginRateLimiter()
        for _ in range(5):
            limiter.check("a@test.com", max_requests=5, window_seconds=300)
        # Different email should still work
        limiter.check("b@test.com", max_requests=5, window_seconds=300)


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password_success(self, admin_client, admin_user):
        admin_user.hashed_password = hash_password("OldPassword1")
        response = await admin_client.post(
            "/api/auth/change-password",
            json={"current_password": "OldPassword1", "new_password": "NewPassword1"},
        )
        assert response.status_code == 200
        assert response.json() == {"message": "Password updated"}

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, admin_client, admin_user):
        admin_user.hashed_password = hash_password("OldPassword1")
        response = await admin_client.post(
            "/api/auth/change-password",
            json={"current_password": "WrongPassword", "new_password": "NewPassword1"},
        )
        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_change_password_too_short(self, admin_client, admin_user):
        admin_user.hashed_password = hash_password("OldPassword1")
        response = await admin_client.post(
            "/api/auth/change-password",
            json={"current_password": "OldPassword1", "new_password": "short"},
        )
        assert response.status_code == 422


class TestMeEndpoint:
    @pytest.mark.asyncio
    async def test_me_returns_current_user(self, admin_client):
        response = await admin_client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "admin@test.com"
        assert data["full_name"] == "Admin Test"
        assert data["role"] == "admin"
