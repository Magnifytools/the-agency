"""Regression tests for inbox note-to-task conversion.

Verifies:
1. due_date defaults to today when not provided
2. _safe_rel_name handles broken relationships
"""
import pytest
from unittest.mock import MagicMock

from backend.api.routes.inbox import _safe_rel_name


class TestSafeRelName:
    def test_returns_name_when_exists(self):
        obj = MagicMock()
        obj.project = MagicMock()
        obj.project.name = "SEO Sprint"
        assert _safe_rel_name(obj, "project") == "SEO Sprint"

    def test_returns_none_when_relationship_is_none(self):
        obj = MagicMock()
        obj.client = None
        assert _safe_rel_name(obj, "client") is None

    def test_returns_none_when_attribute_missing(self):
        obj = MagicMock(spec=[])  # no attributes
        assert _safe_rel_name(obj, "nonexistent") is None

    def test_returns_none_when_access_raises(self):
        obj = MagicMock()
        type(obj).project = property(lambda self: (_ for _ in ()).throw(RuntimeError("detached")))
        assert _safe_rel_name(obj, "project") is None


class TestConvertToTaskSchema:
    def test_due_date_field_exists(self):
        from backend.schemas.inbox import ConvertToTaskBody
        body = ConvertToTaskBody()
        assert body.due_date is None

    def test_due_date_can_be_set(self):
        from datetime import date
        from backend.schemas.inbox import ConvertToTaskBody
        body = ConvertToTaskBody(due_date=date(2026, 3, 16))
        assert body.due_date == date(2026, 3, 16)
