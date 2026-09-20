import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_reconciliation_runs_immediately_before_first_sleep(monkeypatch):
    from backend.startup import background_tasks

    generate = AsyncMock()
    monkeypatch.setattr(background_tasks, "_generate_recurring_instances", generate)

    async def stop_after_first_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(background_tasks.asyncio, "sleep", stop_after_first_cycle)
    with pytest.raises(asyncio.CancelledError):
        await background_tasks._recurring_reconciliation_loop()
    generate.assert_awaited_once()
