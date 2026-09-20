"""The new incident producer must stay explicitly gated through rollout."""
from types import SimpleNamespace

import pytest

from backend.config import Settings, settings
from backend.startup import background_tasks


@pytest.mark.parametrize("enabled", [False, True])
def test_incident_worker_only_starts_when_enabled(monkeypatch, enabled):
    assert Settings.model_fields["INCIDENTS_ENABLED"].default is False
    names = []

    def capture(coroutine, *, name):
        names.append(name)
        coroutine.close()
        return SimpleNamespace(add_done_callback=lambda _: None)

    monkeypatch.setattr(background_tasks.asyncio, "create_task", capture)
    monkeypatch.setattr(settings, "INCIDENTS_ENABLED", enabled)
    background_tasks.start_background_tasks()
    assert names.count("operational-incidents") == int(enabled)
