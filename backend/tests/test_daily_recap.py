"""The closing recap must preserve evidence while presenting it once per task."""

from backend.services.daily_recap import grouped_recap, render_unstructured_recap


def fact(key, kind, title, minutes=None, *, task_id=1, client="Fit Generation", project="Contenido", detail=None):
    return {"key": key, "kind": kind, "title": title, "minutes": minutes,
            "task_id": task_id, "client_id": 3 if client else None, "client_name": client,
            "project_id": 4 if project else None, "project_name": project, "detail": detail}


def test_existing_unstructured_daily_groups_repeated_time_and_removes_copied_rows():
    facts = [
        fact("a", "time_logged", "Fichas", 140, detail="140 min registrados el 2026-09-21"),
        fact("b", "time_logged", "Fichas", 99, detail="99 min registrados el 2026-09-21"),
        fact("c", "task_completed", "Fichas", detail="Completada; responsable actual"),
        fact("d", "time_logged", "Typeform", 19, task_id=2, detail="19 min registrados el 2026-09-21"),
        fact("e", "time_logged", "Typeform", 4, task_id=2, detail="4 min registrados el 2026-09-21"),
    ]
    old_text = "&#x20;\n" + "\n".join(f"- {f['title']} — {f['detail']}" for f in facts) + "\nNota propia"

    result = render_unstructured_recap(old_text, facts)

    assert result.count("Fichas") == 1
    assert "Fichas · 239 min" in result
    assert "Typeform · 23 min" in result
    assert "✅ Fichas" in result
    assert "**Fit Generation · Contenido**" in result
    assert "2026-09-21" not in result
    assert "&#x20;" not in result
    assert result.endswith("**Notas del cierre**\nNota propia")


def test_same_title_under_different_clients_remains_separate():
    facts = [fact("a", "time_logged", "Informe", 12),
             fact("b", "time_logged", "Informe", 8, task_id=9, client="Sage", project="SEO")]
    text = grouped_recap(facts)
    assert text.count("Informe") == 2
    assert "Informe · 12 min" in text
    assert "Informe · 8 min" in text


def test_historical_raw_rows_without_snapshots_are_grouped_without_losing_notes():
    old_text = """&#x20;
- Typeform — 19 min registrados el 2026-09-21
- Typeform — 4 min registrados el 2026-09-21
- Preparar update — Fit Generation — Completada; responsable actual
- Preparar update — Fit Generation — 16 min registrados el 2026-09-21
Revisé el envío con Nacho."""

    result = render_unstructured_recap(old_text, [])

    assert "**General**\n- ⏱ Typeform · 23 min" in result
    assert "**Fit Generation**\n- ✅ Preparar update · 16 min" in result
    assert "registrados el" not in result and "&#x20;" not in result
    assert result.endswith("**Notas del cierre**\nRevisé el envío con Nacho.")
