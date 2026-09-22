"""Readable closing recap from saved evidence, without changing historical facts."""

from __future__ import annotations

import re
from collections import OrderedDict
from html import unescape


def _clean(value: object) -> str:
    return unescape(str(value or "")).strip()


def _source_line(line: str, facts: list[dict]) -> bool:
    """Recognise lines copied by the old fact picker, preserving free-form notes."""
    content = re.sub(r"^\s*[-•*]\s*", "", line).strip()
    for fact in facts:
        title = _clean(fact.get("title"))
        if not title or not content.startswith(title):
            continue
        tail = content[len(title):].strip()
        detail = _clean(fact.get("detail"))
        if tail == f"— {detail}" or tail == f"({fact.get('minutes')} min) — {detail}":
            return True
        # Older generated notes sometimes inserted the client between the title
        # and the canonical status/detail. Keep other human edits intact.
        if detail and tail.endswith(detail) and tail.startswith("— "):
            middle = tail[2:-len(detail)].strip(" —")
            if middle in ("", _clean(fact.get("client_name"))):
                return True
    return False


def recap_notes(raw_text: str, facts: list[dict]) -> str:
    """Remove copied evidence rows; all other author wording remains visible."""
    lines = [_clean(line) for line in raw_text.splitlines()]
    kept = [line for line in lines if line and line != "Sin estructurar" and not _source_line(line, facts)]
    return "\n".join(kept).strip()


_LEGACY_TIME = re.compile(r"^\s*[-•*]\s*(.+?)\s+—\s+(\d+) min registrados el \d{4}-\d{2}-\d{2}\s*$")
_LEGACY_COMPLETION = re.compile(r"^\s*[-•*]\s*(.+?)\s+—\s+Completada; responsable actual\s*$")


def _legacy_facts_and_notes(raw_text: str) -> tuple[list[dict], str]:
    """Recognise only the old generated row syntax; retain unmatched author text."""
    facts, notes = [], []
    for index, original in enumerate(raw_text.splitlines()):
        line = _clean(original)
        if not line or line == "Sin estructurar":
            continue
        time_match = _LEGACY_TIME.fullmatch(line)
        completed_match = _LEGACY_COMPLETION.fullmatch(line)
        if not time_match and not completed_match:
            notes.append(line)
            continue
        label = (time_match or completed_match).group(1)
        title, separator, client = label.rpartition(" — ")
        if not separator:
            title, client = label, ""
        facts.append({
            "key": f"legacy:{index}", "kind": "time_logged" if time_match else "task_completed",
            "title": title, "task_id": None, "client_id": None, "client_name": client,
            "project_id": None, "project_name": None,
            "minutes": int(time_match.group(2)) if time_match else None,
        })
    return facts, "\n".join(notes).strip()


def grouped_recap(facts: list[dict]) -> str:
    """Group selected facts by client/project and task, summing exact minutes."""
    groups: OrderedDict[tuple, OrderedDict[tuple, dict]] = OrderedDict()
    for fact in facts:
        client = _clean(fact.get("client_name"))
        project = _clean(fact.get("project_name"))
        group = (fact.get("client_id") or client, fact.get("project_id") or project, client, project)
        tasks = groups.setdefault(group, OrderedDict())
        task_id = fact.get("task_id")
        title = _clean(fact.get("title")) or "Trabajo sin tarea"
        task_key = ("id", task_id) if task_id is not None else ("title", title.casefold())
        row = tasks.setdefault(task_key, {"title": title, "minutes": 0, "kinds": set(), "details": []})
        kind = fact.get("kind")
        row["kinds"].add(kind)
        if kind == "time_logged" and fact.get("minutes") is not None:
            row["minutes"] += int(fact["minutes"])
        elif kind in ("task_waiting", "next_step") and fact.get("detail"):
            detail = _clean(fact["detail"])
            if detail not in row["details"]:
                row["details"].append(detail)

    result = []
    for (_, _, client, project), tasks in groups.items():
        heading = " · ".join(filter(None, (client, project))) or "General"
        result.append(f"**{heading}**")
        for row in tasks.values():
            kinds = row["kinds"]
            marker = ("✅" if "task_completed" in kinds else
                      "🔄" if "task_advanced" in kinds else
                      "⏱" if "time_logged" in kinds else
                      "⏸" if "task_waiting" in kinds else "➡️")
            detail = " · ".join(row["details"])
            suffix = f" · {row['minutes']} min" if row["minutes"] else ""
            if detail:
                suffix += f" · {detail}"
            result.append(f"- {marker} {row['title']}{suffix}")
        result.append("")
    return "\n".join(result).strip()


def render_unstructured_recap(raw_text: str, facts: list[dict]) -> str:
    if not facts:
        facts, notes = _legacy_facts_and_notes(raw_text)
    else:
        notes = recap_notes(raw_text, facts)
    summary = grouped_recap(facts)
    if summary and notes:
        return f"{summary}\n\n**Notas del cierre**\n{notes}"
    if summary:
        return summary
    return notes or "Sin contenido para el cierre del día"
