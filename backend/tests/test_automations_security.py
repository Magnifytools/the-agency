"""Tests for automation rules security — sensitive field masking."""
import pytest
from unittest.mock import MagicMock

from backend.api.routes.automations import (
    _sanitize_action_config,
    _SENSITIVE_ACTION_FIELDS,
)


class TestSanitizeActionConfig:
    def test_masks_webhook_url(self):
        config = {"webhook_url": "https://discord.com/api/webhooks/123/abc", "message": "Hello"}
        result = _sanitize_action_config(config, "send_discord")
        assert result["webhook_url"] == "••••••"
        assert result["message"] == "Hello"

    def test_masks_bot_token(self):
        config = {"bot_token": "xoxb-secret-token", "channel": "#general"}
        result = _sanitize_action_config(config, "send_slack")
        assert result["bot_token"] == "••••••"
        assert result["channel"] == "#general"

    def test_masks_api_key(self):
        config = {"api_key": "sk-12345", "endpoint": "/v1/data"}
        result = _sanitize_action_config(config, "call_api")
        assert result["api_key"] == "••••••"
        assert result["endpoint"] == "/v1/data"

    def test_masks_password(self):
        config = {"password": "super-secret", "username": "admin"}
        result = _sanitize_action_config(config, "any")
        assert result["password"] == "••••••"
        assert result["username"] == "admin"

    def test_empty_sensitive_field_returns_empty_string(self):
        config = {"webhook_url": "", "message": "test"}
        result = _sanitize_action_config(config, "send_discord")
        assert result["webhook_url"] == ""

    def test_none_config_returns_empty_dict(self):
        result = _sanitize_action_config(None, "send_discord")
        assert result == {}

    def test_no_sensitive_fields_passes_through(self):
        config = {"message": "Hello", "channel": "#general", "format": "text"}
        result = _sanitize_action_config(config, "send_discord")
        assert result == config

    def test_does_not_mutate_original(self):
        config = {"webhook_url": "https://secret.url", "message": "test"}
        _sanitize_action_config(config, "send_discord")
        assert config["webhook_url"] == "https://secret.url"

    def test_all_sensitive_fields_covered(self):
        """Verify all sensitive field names are in the set."""
        assert "webhook_url" in _SENSITIVE_ACTION_FIELDS
        assert "bot_token" in _SENSITIVE_ACTION_FIELDS
        assert "api_key" in _SENSITIVE_ACTION_FIELDS
        assert "secret" in _SENSITIVE_ACTION_FIELDS
        assert "password" in _SENSITIVE_ACTION_FIELDS
