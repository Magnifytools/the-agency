"""A dead worker must not prevent cancellation of the remaining workers."""
import asyncio
from unittest.mock import AsyncMock

import pytest


async def test_shutdown_cancels_all_workers_when_one_already_failed(monkeypatch):
    import backend.main as main
    from backend.startup import deployment_schema

    waiting = asyncio.Event()
    cancelled = asyncio.Event()

    async def failed():
        raise RuntimeError("synthetic worker stopped")

    async def alive():
        waiting.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    jobs = [asyncio.create_task(failed()), asyncio.create_task(alive())]
    await waiting.wait()
    monkeypatch.setattr(main, "start_background_tasks", lambda: jobs)
    monkeypatch.setattr(deployment_schema, "check_deployment_ready", AsyncMock())
    lifecycle = main.lifespan(main.app)
    try:
        await anext(lifecycle)
        with pytest.raises(StopAsyncIteration):
            await anext(lifecycle)
        assert cancelled.is_set()
        assert all(job.done() for job in jobs)
    finally:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        await lifecycle.aclose()
