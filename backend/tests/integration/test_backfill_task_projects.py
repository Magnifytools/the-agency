"""Task→project backfill: dry-run touches nothing, apply links only the unambiguous."""
import json
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import Client, ClientStatus, Project, ProjectStatus, Task, TaskPriority, TaskStatus
from backend.scripts import backfill_task_projects

pytestmark = pytest.mark.integration


@pytest.fixture
def use_session(monkeypatch, db_session):
    @asynccontextmanager
    async def local_session():
        yield db_session

    monkeypatch.setattr(backfill_task_projects, "async_session", local_session)


async def _client(db, n_active, status=ClientStatus.active, project_created=datetime(2026, 1, 1)):  # noqa: DTZ001
    client = Client(name=f"Backfill {uuid4().hex[:8]}", status=status)
    db.add(client)
    await db.flush()
    projects = [
        Project(name=f"P{i} {uuid4().hex[:6]}", client_id=client.id, status=ProjectStatus.active,
                created_at=project_created)
        for i in range(n_active)
    ]
    projects.append(Project(name="Old", client_id=client.id, status=ProjectStatus.completed))
    db.add_all(projects)
    await db.flush()
    return client, projects


async def _task(db, client_id, project_id=None, created_at=datetime(2026, 9, 1)):  # noqa: DTZ001
    task = Task(
        title=f"T {uuid4().hex[:6]}", client_id=client_id, project_id=project_id,
        status=TaskStatus.pending, priority=TaskPriority.medium, created_at=created_at,
    )
    db.add(task)
    await db.flush()
    return task


async def _scenario(db):
    single, [only, old] = await _client(db, 1)
    multi, _ = await _client(db, 2)
    none_active, _ = await _client(db, 0)
    finished, _ = await _client(db, 1, status=ClientStatus.finished)
    tasks = {
        "linked": await _task(db, single.id),
        "predates": await _task(db, single.id, created_at=datetime(2025, 6, 1)),  # noqa: DTZ001
        "already": await _task(db, single.id, project_id=old.id),
        "multi": await _task(db, multi.id),
        "none_active": await _task(db, none_active.id),
        "finished": await _task(db, finished.id),
        "no_client": await _task(db, None),
    }
    await db.commit()
    # Plain ids: the dry-run rolls back, which expires every loaded object.
    return single.id, only.id, old.id, {name: task.id for name, task in tasks.items()}


async def _projects(db, tasks):
    rows = (await db.execute(select(Task.id, Task.project_id).where(
        Task.id.in_(list(tasks.values()))
    ))).all()
    by_id = dict(rows)
    return {name: by_id[task_id] for name, task_id in tasks.items()}


async def test_dry_run_reports_without_changing_anything(db_session, use_session, capsys):
    single, only, old, tasks = await _scenario(db_session)
    before = await _projects(db_session, tasks)

    result = await backfill_task_projects.main(apply=False, scope_client_id=single)

    assert [row[0] for row in result["plan"]] == [tasks["linked"], tasks["predates"]]
    assert result["predates_project"] == 1
    assert await _projects(db_session, tasks) == before
    assert "Dry-run only" in capsys.readouterr().out


async def test_skip_reasons_cover_every_orphan(db_session, use_session):
    _single, _only, _old, tasks = await _scenario(db_session)
    result = await backfill_task_projects.main(apply=False, scope_client_id=None)
    planned = {row[0] for row in result["plan"]}
    assert {tasks["linked"], tasks["predates"]} <= planned
    assert not planned & {tasks[k] for k in ("already", "multi", "none_active", "finished", "no_client")}
    assert result["orphans"] == len(result["plan"]) + sum(result["skipped"].values())
    assert all(result["skipped"][k] >= 1 for k in result["skipped"])


async def test_apply_links_only_unambiguous_orphans_and_writes_rollback(
    db_session, use_session, tmp_path,
):
    single, only, old, tasks = await _scenario(db_session)

    result = await backfill_task_projects.main(apply=True, scope_client_id=single, rollback_dir=tmp_path)

    after = await _projects(db_session, tasks)
    assert after["linked"] == after["predates"] == only
    assert after["already"] == old
    assert after["multi"] is after["none_active"] is after["finished"] is after["no_client"] is None
    saved = json.loads(result["rollback_file"].read_text())
    assert saved["linked_task_ids_by_project"] == {str(only): [tasks["linked"], tasks["predates"]]}

    again = await backfill_task_projects.main(apply=True, scope_client_id=single, rollback_dir=tmp_path)
    assert again["plan"] == []  # idempotent
