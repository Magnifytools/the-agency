"""Borrador de IA desde el procedimiento: se guarda como comentario marcado,
no toca la tarea y sólo lleva al prompt lo que quien lo pide puede leer."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.db.models import (
    Client, DigestExternalDeliveryEvent, ExternalDeliveryAction, Task, TaskComment,
    TaskStatus, WeeklyDigest,
)
from backend.services import task_draft

pytestmark = pytest.mark.integration

PROCEDURE = "1. Exportar Search Console\n2. Comparar con el mes anterior\n3. Redactar conclusiones"


class FakeClaude:
    def __init__(self, *, text="## Informe\n\n- [PENDIENTE: clics]", error=None):
        self.calls: list[dict] = []
        self.text, self.error = text, error
        self.messages = self

    def with_options(self, **options):
        self.options = options
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
        )


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from backend.core.rate_limiter import ai_limiter

    ai_limiter._limiter._requests.clear()
    yield


@pytest.fixture
def fake_claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(task_draft, "get_anthropic_client", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def task_with_procedure(db_session, admin_user):
    client = Client(name="Fit Generation", context="Ecommerce de suplementos; foco en tráfico orgánico de blog.")
    db_session.add(client)
    await db_session.flush()
    digest = WeeklyDigest(
        client_id=client.id, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
        created_by=admin_user.id,
        content={"sections": {"done": [{"title": "Migración del blog", "description": "301 revisados"}]}},
    )
    task = Task(title="Informe SEO de octubre", client_id=client.id, status=TaskStatus.pending,
                procedure_text=PROCEDURE, procedure_url="https://docs.example.test/informe")
    db_session.add_all([digest, task])
    await db_session.flush()
    db_session.add(DigestExternalDeliveryEvent(
        digest_id=digest.id, action=ExternalDeliveryAction.confirmed, actor_id=admin_user.id,
        request_key="k-1", request_hash="h" * 64,
    ))
    await db_session.flush()
    return task


async def _comments(db_session, task_id):
    db_session.expire_all()
    return list((await db_session.execute(
        select(TaskComment).where(TaskComment.task_id == task_id)
    )).scalars())


async def test_draft_is_saved_as_ai_comment_and_task_is_untouched(
    admin_client, db_session, task_with_procedure, fake_claude,
):
    tid = task_with_procedure.id
    response = await admin_client.post(f"/api/tasks/{tid}/draft")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_ai_draft"] is True
    assert body["text"].startswith("## Informe")
    assert body["user_name"] == "Admin Integration"

    [call] = fake_claude.calls
    assert call["model"] == "claude-opus-5-5"
    prompt = call["messages"][0]["content"]
    assert PROCEDURE in prompt
    assert "Informe SEO de octubre" in prompt and "Fit Generation" in prompt
    assert "Ecommerce de suplementos" in prompt
    assert "Migración del blog" in prompt
    assert "https://docs.example.test/informe" in prompt
    assert fake_claude.options == {"timeout": task_draft.TIMEOUT_SECONDS, "max_retries": 0}

    [comment] = await _comments(db_session, tid)
    assert comment.is_ai_draft and comment.user_id == admin_client.test_user.id
    await db_session.refresh(task_with_procedure)
    assert task_with_procedure.status == TaskStatus.pending

    listed = (await admin_client.get(f"/api/tasks/{tid}/comments")).json()
    assert [c["is_ai_draft"] for c in listed] == [True]
    normal = await admin_client.post(f"/api/tasks/{tid}/comments", json={"text": "Visto"})
    assert normal.json()["is_ai_draft"] is False


async def test_task_without_procedure_is_rejected_without_calling_claude(
    admin_client, db_session, fake_claude,
):
    task = Task(title="Puntual", status=TaskStatus.pending, procedure_text="  ")
    db_session.add(task)
    await db_session.flush()
    response = await admin_client.post(f"/api/tasks/{task.id}/draft")
    assert response.status_code == 422
    assert fake_claude.calls == []
    assert (await admin_client.post("/api/tasks/999999/draft")).status_code == 404


async def test_retired_task_is_rejected(admin_client, db_session, task_with_procedure, fake_claude):
    task_with_procedure.retired_at = datetime(2026, 10, 1, 9, 0)
    task_with_procedure.retired_reason = "Ya no aplica"
    await db_session.flush()
    response = await admin_client.post(f"/api/tasks/{task_with_procedure.id}/draft")
    assert response.status_code == 409
    assert fake_claude.calls == []


async def test_provider_failure_saves_nothing(
    admin_client, db_session, task_with_procedure, fake_claude,
):
    fake_claude.error = RuntimeError("boom")
    response = await admin_client.post(f"/api/tasks/{task_with_procedure.id}/draft")
    assert response.status_code == 502
    assert "borrador" in response.json()["detail"]
    assert await _comments(db_session, task_with_procedure.id) == []


async def test_empty_answer_is_a_failure(admin_client, db_session, task_with_procedure, fake_claude):
    fake_claude.text = "   "
    response = await admin_client.post(f"/api/tasks/{task_with_procedure.id}/draft")
    assert response.status_code == 502
    assert await _comments(db_session, task_with_procedure.id) == []


async def test_permissions(make_member_client, task_with_procedure, fake_claude):
    reader = await make_member_client([("tasks", True, False), ("clients", True, False)])
    async with reader:
        assert (await reader.post(f"/api/tasks/{task_with_procedure.id}/draft")).status_code == 403
    assert fake_claude.calls == []

    # Puede escribir tareas pero no lee clientes ni resúmenes: el dossier y el
    # último resumen no viajan al prompt (el borrador lo verían otros lectores).
    writer = await make_member_client([("tasks", True, True)])
    async with writer:
        response = await writer.post(f"/api/tasks/{task_with_procedure.id}/draft")
    assert response.status_code == 201, response.text
    prompt = fake_claude.calls[-1]["messages"][0]["content"]
    assert PROCEDURE in prompt and "Fit Generation" in prompt
    assert "Ecommerce de suplementos" not in prompt
    assert "Migración del blog" not in prompt


async def test_revoked_delivery_is_not_used(admin_client, db_session, task_with_procedure, fake_claude):
    digest = (await db_session.execute(
        select(WeeklyDigest).where(WeeklyDigest.client_id == task_with_procedure.client_id)
    )).scalar_one()
    db_session.add(DigestExternalDeliveryEvent(
        digest_id=digest.id, action=ExternalDeliveryAction.revoked,
        actor_id=admin_client.test_user.id, request_key="k-2", request_hash="r" * 64,
    ))
    await db_session.flush()
    response = await admin_client.post(f"/api/tasks/{task_with_procedure.id}/draft")
    assert response.status_code == 201, response.text
    assert "Migración del blog" not in fake_claude.calls[-1]["messages"][0]["content"]
