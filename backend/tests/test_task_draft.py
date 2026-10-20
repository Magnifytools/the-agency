"""Reglas del borrador de IA sin base de datos: presupuesto, recortes y respuestas raras."""
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services import task_draft

FRONT_API = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"


def _context(**extra):
    return {
        "task_title": "Informe", "task_description": "", "procedure_text": "1. Paso",
        "procedure_url": "", "checklist": [], "project_name": None, "client_name": None,
        "client_context": "", "last_report": None, **extra,
    }


def test_timeout_fits_inside_the_front_budget():
    # Sin reintentos: un corte por tiempo sólo se repetiría (CLAUDE.md).
    source = FRONT_API.read_text()
    match = re.search(r"/tasks/\$\{taskId\}/draft`, \{\}, \{ timeout: ([\d_]+) \}", source)
    assert match, "tasksApi.draft debe fijar su propio timeout"
    front_seconds = int(match.group(1).replace("_", "")) / 1000
    assert task_draft.TIMEOUT_SECONDS + 5 < front_seconds
    assert task_draft.MAX_TOKENS >= 6000


def test_prompt_is_bounded_and_skips_empty_blocks():
    prompt = task_draft.build_draft_prompt(_context(
        procedure_text=task_draft._clip("x" * 20000, task_draft.MAX_PROCEDURE_CHARS),
    ))
    assert "[…recortado]" in prompt
    assert len(prompt) < task_draft.MAX_PROCEDURE_CHARS + 1000
    assert "<contexto_cliente>" not in prompt and "<ultimo_resumen_entregado" not in prompt


def _fake(stop_reason, text):
    async def create(**kwargs):
        return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    messages = SimpleNamespace(create=create)
    return SimpleNamespace(with_options=lambda **_: SimpleNamespace(messages=messages))


def test_truncated_answer_is_kept_with_a_warning(monkeypatch):
    monkeypatch.setattr(task_draft, "get_anthropic_client", lambda: _fake("max_tokens", "## Medio"))
    text = asyncio.run(task_draft.generate_task_draft("p"))
    assert text.startswith("## Medio") and "se cortó" in text


def test_refusal_and_missing_key_are_errors(monkeypatch):
    monkeypatch.setattr(task_draft, "get_anthropic_client", lambda: _fake("refusal", ""))
    with pytest.raises(task_draft.TaskDraftError):
        asyncio.run(task_draft.generate_task_draft("p"))

    def missing():
        raise ValueError("ANTHROPIC_API_KEY no configurada")
    monkeypatch.setattr(task_draft, "get_anthropic_client", missing)
    with pytest.raises(task_draft.TaskDraftError, match="no está configurada"):
        asyncio.run(task_draft.generate_task_draft("p"))
