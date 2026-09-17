"""HTTP contracts that must survive Starlette/parser upgrades."""
from httpx import ASGITransport, AsyncClient

from backend.main import app, cors_origins


async def test_extension_download_range_contract(tmp_path, monkeypatch):
    from backend.api.routes import extension

    package = tmp_path / "synthetic.crx"
    package.write_bytes(b"synthetic-extension-bytes")
    monkeypatch.setattr(extension, "_CRX", package)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        partial = await client.get("/extension/agency-manager.crx", headers={"Range": "bytes=0-3"})
        assert partial.status_code == 206
        assert partial.content == b"synt"
        assert partial.headers["content-range"] == "bytes 0-3/25"
        invalid = await client.get("/extension/agency-manager.crx", headers={"Range": "bytes=100-110"})
        assert invalid.status_code == 416


async def test_cookie_cors_preflight_remains_explicit():
    origin = cors_origins[0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options("/api/auth/me", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
