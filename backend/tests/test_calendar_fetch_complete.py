"""Google API is simulated: failed/incomplete pages must never look like an empty calendar."""
from datetime import datetime
from unittest.mock import MagicMock
import pytest
from backend.services import google_calendar_service as service


def test_pages_include_cancellations_and_preserve_offsets(monkeypatch):
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [
        {"items": [{"id": "one", "start": {"dateTime": "2026-09-18T10:00:00+02:00"}}], "nextPageToken": "page2"},
        {"items": [{"id": "cancelled", "status": "cancelled"}, {"id": "two", "start": {"dateTime": "2026-09-18T09:00:00Z"}}]},
    ]
    monkeypatch.setattr(service, "_get_credentials", lambda _: object())
    monkeypatch.setattr(service, "build", lambda *a, **k: api)
    result = service.fetch_events("synthetic", time_min=datetime(2026, 9, 18), time_max=datetime(2026, 9, 25))
    assert [row["google_event_id"] for row in result] == ["one", "cancelled", "two"]
    assert result[1]["cancelled"] is True
    first, second = api.events.return_value.list.call_args_list
    assert first.kwargs["timeMin"] == "2026-09-18T00:00:00+02:00"
    assert first.kwargs["showDeleted"] is True and second.kwargs["pageToken"] == "page2"


def test_partial_failure_raises_instead_of_returning_first_page(monkeypatch):
    api = MagicMock()
    api.events.return_value.list.return_value.execute.side_effect = [{"items": [], "nextPageToken": "page2"}, RuntimeError("failed")]
    monkeypatch.setattr(service, "_get_credentials", lambda _: object())
    monkeypatch.setattr(service, "build", lambda *a, **k: api)
    with pytest.raises(RuntimeError): service.fetch_events("synthetic")


def test_malformed_empty_object_is_not_an_authoritative_empty_calendar(monkeypatch):
    api = MagicMock(); api.events.return_value.list.return_value.execute.return_value = {}
    monkeypatch.setattr(service, "_get_credentials", lambda _: object())
    monkeypatch.setattr(service, "build", lambda *a, **k: api)
    with pytest.raises(ValueError): service.fetch_events("synthetic")


def test_token_exchange_failure_never_logs_provider_body(monkeypatch, caplog):
    import httpx
    from types import SimpleNamespace
    secret = "sentinel-private-provider-response"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: SimpleNamespace(status_code=400, text=secret))
    with pytest.raises(ValueError): service.exchange_code("synthetic-code")
    assert secret not in caplog.text
    assert "HTTP 400" in caplog.text
