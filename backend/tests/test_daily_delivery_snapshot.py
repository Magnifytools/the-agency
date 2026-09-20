"""Delivery snapshots distinguish evidence from free notes and old formats."""
from datetime import date
from types import SimpleNamespace

import pytest

from backend.services.deliveries import render_snapshot


@pytest.mark.parametrize("task,facts,marker", [
    ({"description": "Pendiente de respuesta", "fact_keys": []}, [], "•"),
    ({"description": "Pendiente de respuesta", "fact_keys": ["waiting:1"]},
     [{"key": "waiting:1", "kind": "task_waiting"}], "⏸"),
    ({"description": "Texto histórico"}, [], "✅"),
])
def test_delivery_snapshot_uses_provenance_even_without_selected_facts(task, facts, marker):
    source = SimpleNamespace(
        user=SimpleNamespace(full_name="Persona de prueba"),
        date=date(2026, 9, 20), raw_text="Nota guardada", source_facts=facts,
        parsed_data={"projects": [], "general": [task], "tomorrow": []},
    )
    _, text = render_snapshot("daily", source)
    assert f"{marker} {task['description']}" in text
    if marker != "✅":
        assert "✅" not in text
