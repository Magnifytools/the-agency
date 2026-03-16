"""
Permission matrix tests.
Covers: vault RBAC, inbox access, capacity admin-only, users sanitization, CSRF.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Vault ────────────────────────────────────────────────────────────────────

class TestVaultRBAC:
    @pytest.mark.asyncio
    async def test_vault_admin_allowed(self, admin_client):
        """Admin can list vault assets."""
        with patch("backend.api.routes.agency_vault.get_db"):
            response = await admin_client.get("/api/vault/assets")
        # 200 or 422/500 from mock DB — NOT 403
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_vault_member_forbidden(self, member_client):
        """Member gets 403 on vault assets."""
        response = await member_client.get("/api/vault/assets")
        assert response.status_code == 403


# ── Capacity ─────────────────────────────────────────────────────────────────

class TestCapacityRBAC:
    @pytest.mark.asyncio
    async def test_capacity_admin_allowed(self, admin_client):
        """Admin can access capacity endpoint."""
        response = await admin_client.get("/api/dashboard/capacity")
        assert response.status_code != 403

    @pytest.mark.asyncio
    async def test_capacity_member_forbidden(self, member_client):
        """Member gets 403 on capacity (admin-only after fix)."""
        response = await member_client.get("/api/dashboard/capacity")
        assert response.status_code == 403


# ── Users ────────────────────────────────────────────────────────────────────

class TestUsersEndpoint:
    @pytest.mark.asyncio
    async def test_users_member_gets_sanitized_data(self, member_client):
        """Member can list users but only gets id + full_name, no email/role/rate."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        # Simulate 2 users returned from DB
        from unittest.mock import MagicMock
        from backend.db.models import User, UserRole
        u1 = MagicMock(spec=User)
        u1.id = 1
        u1.full_name = "Alice Admin"
        u1.email = "alice@magnify.ing"
        u1.role = UserRole.admin
        u1.hourly_rate = 50.0
        u1.is_active = True
        u1.preferences = None
        u1.region = None
        u1.locality = None
        u1.permissions = []

        u2 = MagicMock(spec=User)
        u2.id = 2
        u2.full_name = "Bob Member"
        u2.email = "bob@magnify.ing"
        u2.role = UserRole.member
        u2.hourly_rate = 30.0
        u2.is_active = True
        u2.preferences = None
        u2.permissions = []

        # Mock the DB execute chain
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [u1, u2]
        mock_db.execute = AsyncMock(side_effect=[count_result, users_result])

        app.dependency_overrides[get_db] = lambda: mock_db

        response = await member_client.get("/api/users")
        assert response.status_code == 200
        items = response.json()["items"]
        for item in items:
            assert item.get("email") is None, "email must not be exposed to member"
            assert item.get("role") is None, "role must not be exposed to member"
            assert item.get("hourly_rate") is None, "hourly_rate must not be exposed"
            assert "id" in item
            assert "full_name" in item

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_users_admin_gets_full_data(self, admin_client):
        """Admin gets full user data including email and role."""
        from backend.db.database import get_db
        from backend.main import app

        mock_db = AsyncMock()
        from unittest.mock import MagicMock
        from backend.db.models import User, UserRole
        u1 = MagicMock(spec=User)
        u1.id = 1
        u1.full_name = "Alice Admin"
        u1.email = "alice@magnify.ing"
        u1.role = UserRole.admin
        u1.hourly_rate = 50.0
        u1.is_active = True
        u1.preferences = None
        u1.region = None
        u1.locality = None
        u1.permissions = []

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [u1]
        mock_db.execute = AsyncMock(side_effect=[count_result, users_result])

        app.dependency_overrides[get_db] = lambda: mock_db

        response = await admin_client.get("/api/users")
        assert response.status_code == 200
        items = response.json()["items"]
        assert items[0]["email"] == "alice@magnify.ing"
        assert items[0]["role"] == "admin"

        app.dependency_overrides.clear()


# ── Inbox ────────────────────────────────────────────────────────────────────

class TestInboxCount:
    @pytest.mark.asyncio
    async def test_inbox_count_admin_200(self, admin_client):
        """Admin gets 200 on inbox count."""
        response = await admin_client.get("/api/inbox/count")
        # 200 or 500 from mock DB — NOT 403/401
        assert response.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_inbox_count_member_200(self, member_client):
        """Member also gets 200 on inbox count (not 403)."""
        response = await member_client.get("/api/inbox/count")
        assert response.status_code not in (401, 403)


# ── CSRF ─────────────────────────────────────────────────────────────────────

class TestCSRFProtection:
    @pytest.mark.asyncio
    async def test_mutation_without_csrf_blocked_for_cookie_auth(self):
        """POST with cookie auth but no CSRF token is rejected."""
        from httpx import AsyncClient, ASGITransport
        from backend.main import app

        # Simulate cookie-only auth (no Authorization header).
        # Must use the real cookie name (agency_access_token) so the CSRF
        # middleware sees it as cookie-based auth and enforces the check.
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"agency_access_token": "fake-jwt-cookie"},
        ) as client:
            response = await client.post(
                "/api/tasks",
                json={"title": "test"},
                # No X-CSRF-Token header, no Authorization header
            )
        assert response.status_code == 403
        assert "CSRF" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_bearer_token_auth_skips_csrf(self, admin_client):
        """Bearer token requests are not subject to CSRF check."""
        # admin_client uses dependency_overrides (no real cookie),
        # so CSRF middleware won't trigger — request goes through.
        # We send an empty body to get 422 validation error (not 403 CSRF).
        response = await admin_client.post(
            "/api/inbox",
            json={},  # missing required fields → 422, no DB/background tasks
        )
        # Not blocked by CSRF (got 422 for bad body, not 403 for CSRF)
        assert response.status_code != 403 or "CSRF" not in response.text

    @pytest.mark.asyncio
    async def test_login_exempt_from_csrf(self):
        """Login endpoint is exempt from CSRF even with cookie present."""
        from httpx import AsyncClient, ASGITransport
        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"agency_access_token": "fake-jwt-cookie"},
        ) as client:
            response = await client.post(
                "/api/auth/login",
                json={"email": "x@x.com", "password": "wrong"},
            )
        # Should NOT be blocked by CSRF (may be 401 for bad credentials)
        assert response.status_code != 403 or "CSRF" not in response.text

    @pytest.mark.asyncio
    async def test_get_requests_exempt_from_csrf(self, member_client):
        """GET requests are always CSRF-safe."""
        response = await member_client.get("/api/inbox/count")
        assert response.status_code not in (401, 403)


# ── Admin-only routes ────────────────────────────────────────────────────────

class TestAdminOnlyRoutes:
    """Smoke test: member gets 403 on all admin-only API endpoints."""

    ADMIN_ONLY_ENDPOINTS = [
        ("GET", "/api/vault/assets"),
        ("GET", "/api/dashboard/capacity"),
        ("GET", "/api/users/1"),          # get single user (admin-only)
        # DELETE /api/users/1 not implemented — no endpoint, would return 405
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
    async def test_member_forbidden(self, member_client, method, path):
        response = await member_client.request(method, path)
        assert response.status_code == 403, (
            f"Expected 403 for member on {method} {path}, got {response.status_code}"
        )
