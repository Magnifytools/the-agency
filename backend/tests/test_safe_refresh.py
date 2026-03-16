"""Tests for the safe_refresh utility and error handler middleware."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.api.utils.db_helpers import safe_refresh


class TestSafeRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self):
        """safe_refresh calls db.refresh normally when it succeeds."""
        db = AsyncMock()
        obj = MagicMock()
        await safe_refresh(db, obj)
        db.refresh.assert_awaited_once_with(obj)

    @pytest.mark.asyncio
    async def test_refresh_with_attributes(self):
        """safe_refresh passes attribute_names to db.refresh."""
        db = AsyncMock()
        obj = MagicMock()
        await safe_refresh(db, obj, ["project", "client"])
        db.refresh.assert_awaited_once_with(obj, ["project", "client"])

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_raise(self):
        """safe_refresh swallows exceptions from db.refresh."""
        db = AsyncMock()
        db.refresh.side_effect = Exception("relationship load failed")
        obj = MagicMock()

        # Should NOT raise
        await safe_refresh(db, obj, log_context="test_case")

    @pytest.mark.asyncio
    async def test_refresh_failure_with_sqlalchemy_error(self):
        """safe_refresh swallows SQLAlchemy-specific errors."""
        db = AsyncMock()
        db.refresh.side_effect = RuntimeError("InvalidRequestError: no such column")
        obj = MagicMock()

        await safe_refresh(db, obj, log_context="evidence_upload")
        # No exception should propagate
