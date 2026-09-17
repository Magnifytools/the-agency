"""Real-DB session flows for the JWT/framework dependency upgrade."""
from httpx import ASGITransport, AsyncClient
import pytest

from backend.config import settings
from backend.core.security import create_access_token, decode_access_token
from backend.core.token_blacklist import token_blacklist


@pytest.fixture(autouse=True)
def isolate_revocations():
    token_blacklist.clear()
    yield
    token_blacklist.clear()


async def test_login_cookie_csrf_bearer_and_logout(app_with_db, admin_user):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as browser:
        login = await browser.post("/api/auth/login", json={
            "email": admin_user.email, "password": "test-password",
        })
        assert login.status_code == 200
        token = login.json()["access_token"]
        claims = decode_access_token(token)
        assert claims["sub"] == str(admin_user.id)
        assert claims["jti"] and claims["exp"]
        cookies = login.headers.get_list("set-cookie")
        assert any(settings.AUTH_COOKIE_NAME in cookie and "httponly" in cookie.lower() for cookie in cookies)
        assert browser.cookies[settings.AUTH_COOKIE_NAME] == token
        csrf = browser.cookies[settings.CSRF_COOKIE_NAME]
        assert (await browser.get("/api/auth/me")).json()["id"] == admin_user.id

        body = {"current_password": "test-password", "new_password": "New-test-password-123"}
        rejected = await browser.post("/api/auth/change-password", json=body)
        assert rejected.status_code == 403
        assert "CSRF" in rejected.json()["detail"]
        changed = await browser.post("/api/auth/change-password", json=body, headers={"X-CSRF-Token": csrf})
        assert changed.status_code == 200

        async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test",
                               headers={"Authorization": f"Bearer {token}"}) as extension:
            assert (await extension.get("/api/auth/me")).status_code == 200
            logout = await browser.post("/api/auth/logout")
            assert logout.status_code == 204
            assert settings.AUTH_COOKIE_NAME not in browser.cookies
            assert settings.CSRF_COOKIE_NAME not in browser.cookies
            assert token_blacklist.is_blacklisted(claims["jti"])
            revoked = await extension.get("/api/auth/me")
            assert revoked.status_code == 401
            assert "revoked" in revoked.json()["detail"]


async def test_bearer_logout_and_inactive_user(app_with_db, admin_user, db_session):
    token = create_access_token({"sub": str(admin_user.id)})
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test",
                           headers={"Authorization": f"Bearer {token}"}) as extension:
        assert (await extension.post("/api/auth/logout")).status_code == 204
        assert (await extension.get("/api/auth/me")).status_code == 401
        admin_user.is_active = False
        await db_session.flush()
        fresh_token = create_access_token({"sub": str(admin_user.id)})
        extension.headers["Authorization"] = f"Bearer {fresh_token}"
        assert (await extension.get("/api/auth/me")).status_code == 403


async def test_real_jwt_does_not_bypass_module_permissions(member_client):
    assert (await member_client.get("/api/clients")).status_code == 403


async def test_cookie_csrf_still_blocks_malformed_host(app_with_db, admin_user):
    # Bounded header regression, no load/DoS traffic. The path used by CSRF
    # must remain the actual API path even when Host includes path delimiters.
    token = create_access_token({"sub": str(admin_user.id)})
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test",
                           cookies={settings.AUTH_COOKIE_NAME: token}) as browser:
        response = await browser.post("/api/auth/change-password", headers={"Host": "test/?"},
                                      json={"current_password": "test-password", "new_password": "New-test-password-123"})
        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]


@pytest.mark.parametrize("size", [32, 1024 * 1024 + 1])
async def test_multipart_task_attachment_roundtrip(admin_client, db_session, size):
    from backend.db.models import Task

    task = Task(title="Dependency upload test")
    db_session.add(task)
    await db_session.flush()
    content = b"x" * size
    response = await admin_client.post(f"/api/tasks/{task.id}/attachments",
                                       files={"file": ("sample.txt", content, "text/plain")})
    assert response.status_code == 201
    attachment = response.json()
    assert attachment["size_bytes"] == size
    downloaded = await admin_client.get(f"/api/tasks/{task.id}/attachments/{attachment['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == content
