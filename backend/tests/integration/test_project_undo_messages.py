"""Project undo explains recurrence and returns a renderable conflict message."""
import pytest

from backend.api.routes.changes import _recent_label
from backend.db.models import ChangeLog, Client, Project, ProjectStatus, Task
from backend.services.change_journal import paused


@pytest.mark.parametrize("before,after,expected", [
    ("active", "completed", "las plantillas no pausadas podrán crear tareas desde hoy"),
    ("on_hold", "cancelled", "conservando sus pausas"),
    ("completed", "active", "sólo si no quedan tareas abiertas ni cronómetros"),
    ("active", "on_hold", None),
])
def test_inverse_description_is_derived_without_mutating_journal(before, after, expected):
    entry = ChangeLog(label="Proyecto editado", operations=[{
        "entity_type": "project", "action": "update", "before": {"status": before},
        "after": {"status": after},
    }])
    label = _recent_label(entry)
    assert (expected in label) if expected else label == entry.label
    assert entry.label == "Proyecto editado"


async def test_recent_explains_reopen_and_blocked_inverse_returns_text(
    admin_client, db_session,
):
    client = Client(name="Undo explanation")
    project = Project(name="Undo explanation", client=client, status=ProjectStatus.active)
    db_session.add_all([client, project])
    await db_session.commit()
    project_id = project.id
    preview = (await admin_client.get(f"/api/projects/{project_id}/close-preview", params={"target": "completed"})).json()
    closed = await admin_client.post(f"/api/projects/{project_id}/close", json={
        "target": "completed", "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })
    assert closed.status_code == 200, closed.text
    recent = (await admin_client.get("/api/changes/recent")).json()
    assert "las plantillas no pausadas" in recent[0]["label"]
    reopened = await admin_client.post(f"/api/changes/{recent[0]['id']}/undo")
    assert reopened.status_code == 200, reopened.text
    # A separate real close/reopen journal provides the inverse to block.
    preview = (await admin_client.get(f"/api/projects/{project_id}/close-preview", params={"target": "completed"})).json()
    assert (await admin_client.post(f"/api/projects/{project_id}/close", json={
        "target": "completed", "expected_updated_at": preview["expected_updated_at"],
        "preview_revision": preview["preview_revision"],
    })).status_code == 200
    preview = (await admin_client.get(f"/api/projects/{project_id}/reopen-preview")).json()
    assert (await admin_client.post(f"/api/projects/{project_id}/reopen", json={
        "expected_updated_at": preview["expected_updated_at"], "preview_revision": preview["preview_revision"],
    })).status_code == 200
    recent = (await admin_client.get("/api/changes/recent")).json()
    undo_id = recent[0]["id"]
    with paused():
        db_session.add(Task(title="Later work", project_id=project_id))
        await db_session.commit()
    result = await admin_client.post(f"/api/changes/{undo_id}/undo")
    assert result.status_code == 409, result.text
    assert isinstance(result.json()["detail"], str)
    assert "tareas abiertas o cronómetros" in result.json()["detail"]
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).status == ProjectStatus.active
    assert (await db_session.get(ChangeLog, undo_id)).undone_at is None
