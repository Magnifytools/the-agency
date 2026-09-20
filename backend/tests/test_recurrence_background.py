import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_coordinated_reconciliation_runs_due_cycle_before_first_sleep(monkeypatch):
    from backend.services import job_runtime
    from backend.startup import background_tasks

    generate = AsyncMock()
    definition = SimpleNamespace(
        spec=SimpleNamespace(key="recurrence", interval_seconds=300),
    )

    async def run_job(_engine, spec, operation):
        assert spec is definition.spec
        await operation()
        return True

    async def stop_after_first_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(job_runtime, "run_job", run_job)
    monkeypatch.setattr(background_tasks.asyncio, "sleep", stop_after_first_cycle)
    with pytest.raises(asyncio.CancelledError):
        await background_tasks._coordinated_job_loop(definition, generate)
    generate.assert_awaited_once()
