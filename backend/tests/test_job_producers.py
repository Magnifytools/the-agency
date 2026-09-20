import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.job_runtime import JobFailure


@pytest.mark.asyncio
async def test_incident_cycle_reports_partial_recipient_failure(monkeypatch):
    from backend.services import incidents
    from backend.startup import background_tasks

    monkeypatch.setattr(
        incidents,
        "reconcile_all",
        AsyncMock(return_value={"recipients": 2, "created": 1, "changed": 0, "failed": 1}),
    )
    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._incident_once()


@pytest.mark.asyncio
async def test_scheduled_cycle_requests_aggregate_failure_reporting(monkeypatch):
    from backend.services import scheduled_communications
    from backend.startup import background_tasks

    run = AsyncMock(return_value=3)
    monkeypatch.setattr(scheduled_communications, "run_scheduler_once", run)
    await background_tasks._scheduled_communications_once()
    assert run.await_args.kwargs == {"raise_on_error": True}


@pytest.mark.asyncio
async def test_engine_cycle_turns_component_failures_into_partial_health(monkeypatch):
    from backend.services import engine_sync_service
    from backend.startup import background_tasks

    monkeypatch.setattr(
        engine_sync_service,
        "sync_engine_metrics",
        AsyncMock(return_value={"synced": 1, "failed": 2}),
    )
    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._engine_sync_once()


@pytest.mark.asyncio
async def test_engine_summary_and_alert_failures_are_counted(monkeypatch):
    from backend.services import engine_sync_service as service

    client = SimpleNamespace(id=7, engine_project_id=99)

    class Result:
        def scalars(self):
            return self

        def all(self):
            return [client]

    class Session:
        async def execute(self, _statement):
            return Result()

        async def commit(self):
            return None

    @asynccontextmanager
    async def session_factory():
        yield Session()

    class Response:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or {}

        def json(self):
            return self._payload

    class Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            if url.endswith("/metrics"):
                return Response(200, {"content_count": 4})
            if url.endswith("/summary"):
                return Response(503)
            raise OSError("synthetic provider outage")

    monkeypatch.setattr(service, "async_session", session_factory)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **_kwargs: Http())
    monkeypatch.setattr(service.settings, "ENGINE_API_URL", "https://engine.invalid")
    monkeypatch.setattr(service.settings, "ENGINE_SERVICE_KEY", "synthetic")

    result = await service.sync_engine_metrics()
    assert result == {"synced": 1, "failed": 2}
    assert client.engine_content_count == 4


@pytest.mark.asyncio
async def test_delivery_health_is_rate_limited_without_changing_queue_work(monkeypatch):
    from backend.services import deliveries, job_runtime_status

    calls = 0

    async def run_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return True

    observations = AsyncMock()
    sleeps = 0

    async def sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(deliveries, "run_once", run_once)
    monkeypatch.setattr(deliveries.asyncio if hasattr(deliveries, "asyncio") else asyncio, "sleep", sleep)
    monkeypatch.setattr(job_runtime_status, "record_delivery_cycle", observations)
    monkeypatch.setattr("time.monotonic", lambda: 100.0)

    with pytest.raises(asyncio.CancelledError):
        await deliveries.delivery_loop()

    assert calls == 3
    assert [call.kwargs for call in observations.await_args_list] == [
        {"failed": False},
    ]


@pytest.mark.asyncio
async def test_delivery_failure_is_observed_but_monitor_failure_does_not_replay(monkeypatch):
    from backend.services import deliveries, job_runtime_status

    run = AsyncMock(side_effect=RuntimeError("synthetic dispatch failure"))
    observe = AsyncMock(side_effect=RuntimeError("synthetic monitor failure"))

    async def sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(deliveries, "run_once", run)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(job_runtime_status, "record_delivery_cycle", observe)

    with pytest.raises(asyncio.CancelledError):
        await deliveries.delivery_loop()

    run.assert_awaited_once()
    observe.assert_awaited_once()
    assert observe.await_args.kwargs == {"failed": True}

@pytest.mark.asyncio
@pytest.mark.parametrize("raise_on_error", [False, True])
async def test_scheduler_finishes_other_policies_before_optional_partial_failure(
    monkeypatch, raise_on_error,
):
    from backend.services import scheduled_communications as service

    planned = []

    async def plan(_db, policy, _now):
        planned.append(policy.id)
        if policy.id == 1:
            raise RuntimeError("synthetic policy failure")

    monkeypatch.setattr(service.settings, "SCHEDULED_COMMUNICATIONS_ENABLED", True)
    monkeypatch.setattr(service, "plan_policy", plan)

    class ScalarRows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class Session:
        def __init__(self, scalar_values=None, policy_id=None):
            self.scalar_values = scalar_values
            self.policy_id = policy_id
            self.committed = False
            self.rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalars(self, _statement):
            return ScalarRows(self.scalar_values or [])

        async def get(self, _model, ident, **_kwargs):
            return SimpleNamespace(id=ident, enabled=True)

        async def commit(self):
            self.committed = True

        async def rollback(self):
            self.rolled_back = True

    sessions = iter([
        Session([1, 2]),
        Session(policy_id=1),
        Session(policy_id=2),
        Session([]),
        Session([]),
    ])

    def factory():
        return next(sessions)

    if raise_on_error:
        with pytest.raises(JobFailure, match="partial_failure"):
            await service.run_scheduler_once(factory, raise_on_error=True)
    else:
        assert await service.run_scheduler_once(factory) == 0
    assert planned == [1, 2]


def test_startup_loops_match_enabled_catalog(monkeypatch):
    from backend.config import settings
    from backend.services.job_catalog import job_definitions
    from backend.startup import background_tasks

    captured = []

    def create_task(coroutine, *, name):
        captured.append(name)
        coroutine.close()
        return SimpleNamespace(add_done_callback=lambda _callback: None)

    monkeypatch.setattr(background_tasks.asyncio, "create_task", create_task)
    tasks = background_tasks.start_background_tasks()
    assert len(tasks) == len(captured)

    names = {
        "incidents": "operational-incidents",
        "engine": "engine-sync",
        "holded": "holded-sync",
        "advanced_reset": "advanced-reset",
        "recurrence": "recurring-reconcile",
        "overdue_automations": "overdue-automations",
        "scheduled_communications": "scheduled-communications",
        "calendar": "calendar-sync",
        "retention": "retention-cleanup",
    }
    definitions = {definition.spec.key: definition for definition in job_definitions()}
    expected = {
        names[key] for key, definition in definitions.items()
        if key != "deliveries" and definition.enabled
    }
    if settings.DELIVERY_WORKER_ENABLED:
        expected.add("manual-deliveries")
    assert set(captured) == expected
    assert definitions["overdue_automations"].spec.run_on_startup is False

@pytest.mark.asyncio
async def test_holded_cycle_continues_stages_then_reports_partial(monkeypatch):
    from backend.api.routes import holded
    from backend.db import database
    from backend.startup import background_tasks

    called = []

    async def contacts(**_kwargs):
        called.append("contacts")
        raise RuntimeError("synthetic contacts failure")

    async def invoices(**_kwargs):
        called.append("invoices")

    async def expenses(**_kwargs):
        called.append("expenses")

    @asynccontextmanager
    async def session_factory():
        yield object()

    monkeypatch.setattr(holded, "sync_contacts", contacts)
    monkeypatch.setattr(holded, "sync_invoices", invoices)
    monkeypatch.setattr(holded, "sync_expenses", expenses)
    monkeypatch.setattr(database, "async_session", session_factory)

    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._holded_sync_once()
    assert called == ["contacts", "invoices", "expenses"]


@pytest.mark.asyncio
async def test_calendar_cycle_continues_users_then_reports_partial(monkeypatch):
    from backend.api.routes import google_calendar
    from backend.db import database
    from backend.startup import background_tasks

    users = {
        1: SimpleNamespace(
            id=1, full_name="First Person", short_name="First",
            email="first@agency.local",
        ),
        2: SimpleNamespace(
            id=2, full_name="Second Person", short_name="Second",
            email="second@agency.local",
        ),
    }
    called = []

    class ScalarRows:
        def all(self):
            return [1, 2]

    class Session:
        async def scalars(self, _statement):
            return ScalarRows()

        async def get(self, _model, ident):
            return users[ident]

    @asynccontextmanager
    async def session_factory():
        yield Session()

    async def sync(_db, user):
        called.append(user.id)
        if user.id == 1:
            raise RuntimeError("synthetic calendar failure")
        return 1

    monkeypatch.setattr(database, "async_session", session_factory)
    monkeypatch.setattr(google_calendar, "sync_user_events", sync)

    with pytest.raises(JobFailure, match="partial_failure"):
        await background_tasks._sync_calendars_once()
    assert called == [1, 2]
