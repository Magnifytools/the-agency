from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from backend.api.middleware.usage_tracker import UsageTrackerMiddleware


class _RecordingSession:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        self.commits += 1


def _request(path: str, method: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
        "root_path": "",
    })


async def _dispatch(monkeypatch, path: str, method: str = "GET"):
    from backend.db import database

    rows = []
    session = _RecordingSession(rows)
    monkeypatch.setattr(database, "async_session", lambda: session)
    request = _request(path, method)

    async def call_next(req):
        req.state.user_id = 17
        req.scope["route"] = SimpleNamespace(path=path)
        return Response(status_code=204)

    middleware = UsageTrackerMiddleware(lambda *_args: None)
    response = await middleware.dispatch(request, call_next)
    return response, rows, session.commits


async def test_active_timer_poll_is_not_recorded_as_human_usage(monkeypatch):
    response, rows, commits = await _dispatch(
        monkeypatch, "/api/timer/active", "GET"
    )

    assert response.status_code == 204
    assert rows == []
    assert commits == 0


@pytest.mark.parametrize("action", ["start", "pause", "resume", "stop"])
async def test_timer_actions_remain_recorded(monkeypatch, action):
    path = f"/api/timer/{action}"
    response, rows, commits = await _dispatch(monkeypatch, path, "POST")

    assert response.status_code == 204
    assert commits == 1
    assert len(rows) == 1
    assert rows[0].route_template == path
    assert rows[0].method == "POST"
    assert rows[0].user_id == 17
