"""Tests for the global error handler middleware."""
import pytest
from unittest.mock import MagicMock

from backend.api.middleware.error_handler import unhandled_exception_handler


class TestErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_json_500_with_ref(self):
        """Error handler returns structured JSON with correlation ID."""
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/tasks"
        request.state = MagicMock()
        request.state.user_id = 42

        response = await unhandled_exception_handler(
            request, RuntimeError("unexpected db error")
        )

        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert "ref" in body
        assert len(body["ref"]) == 8
        assert body["detail"] == "Error interno del servidor"

    @pytest.mark.asyncio
    async def test_handles_missing_user_id(self):
        """Error handler works when request.state has no user_id."""
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/evidence"
        request.state = MagicMock(spec=[])  # no user_id attribute

        response = await unhandled_exception_handler(
            request, ValueError("bad value")
        )

        assert response.status_code == 500
