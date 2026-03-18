"""Tests for the safe_refresh utility and error handler middleware."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.api.utils.db_helpers import safe_refresh, reload_for_response


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
        """safe_refresh swallows exceptions and expunges the object."""
        db = AsyncMock()
        db.refresh.side_effect = Exception("relationship load failed")
        db.expunge = MagicMock()  # expunge is sync, not async
        obj = MagicMock()

        # Should NOT raise
        await safe_refresh(db, obj, log_context="test_case")
        # Object should be expunged from session to prevent lazy-load 500s
        db.expunge.assert_called_once_with(obj)

    @pytest.mark.asyncio
    async def test_refresh_failure_with_sqlalchemy_error(self):
        """safe_refresh swallows SQLAlchemy-specific errors and expunges."""
        db = AsyncMock()
        db.refresh.side_effect = RuntimeError("InvalidRequestError: no such column")
        db.expunge = MagicMock()  # expunge is sync
        obj = MagicMock()

        await safe_refresh(db, obj, log_context="evidence_upload")
        # No exception should propagate
        db.expunge.assert_called_once_with(obj)

    @pytest.mark.asyncio
    async def test_refresh_failure_expunge_also_fails(self):
        """If both refresh and expunge fail, safe_refresh still doesn't raise."""
        db = AsyncMock()
        db.refresh.side_effect = Exception("refresh failed")
        db.expunge = MagicMock(side_effect=Exception("already detached"))
        obj = MagicMock()

        # Should NOT raise even if expunge fails
        await safe_refresh(db, obj, log_context="double_failure")


class TestReloadForResponse:
    @pytest.mark.asyncio
    async def test_reload_returns_object(self):
        """reload_for_response fetches a real model by ID."""
        from backend.db.models import NewsSource

        mock_source = MagicMock(spec=NewsSource)
        mock_source.id = 42

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        db.execute.return_value = mock_result

        result = await reload_for_response(db, NewsSource, 42)
        assert result == mock_source
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reload_returns_none_when_not_found(self):
        """reload_for_response returns None if object not found."""
        from backend.db.models import NewsSource

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await reload_for_response(db, NewsSource, 999)
        assert result is None
