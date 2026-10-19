"""Texto compacto para el modelo.

Las respuestas de la API traen decenas de campos por tarea. Volcarlas enteras
gasta contexto y esconde lo importante, así que cada entidad se resume en una
línea con su id (para poder actuar sobre ella después).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, tzinfo
from typing import Any

TASK_STATUS = {
    "backlog": "backlog",
    "pending": "pendiente",
    "in_progress": "en curso",
    "waiting": "esperando",
    "in_review": "en revisión",
    "advanced": "avanzada hoy",
    "completed": "completada",
}

PRIORITY = {"urgent": "urgente", "high": "alta", "medium": "media", "low": "baja"}

PROJECT_STATUS = {
    "planning": "planificación",
    "active": "activo",
    "on_hold": "en pausa",
    "completed": "terminado",
    "cancelled": "cancelado",
}


def day(value: str | None) -> str | None:
    """'2026-10-18T09:00:00' -> '2026-10-18'."""
    return value[:10] if value else None


def hours(minutes: float | None) -> str:
    minutes = int(minutes or 0)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


def task_line(t: dict[str, Any]) -> str:
    status = TASK_STATUS.get(t.get("status"), t.get("status"))
    priority = PRIORITY.get(t.get("priority"), t.get("priority"))
    parts = [f"#{t['id']} {t['title']} [{status} · {priority}]"]

    where = " / ".join(p for p in (t.get("client_name"), t.get("project_name")) if p)
    if where:
        parts.append(where)
    parts.append(t.get("assigned_user_name") or "sin asignar")
    if t.get("due_date"):
        parts.append(f"vence {day(t['due_date'])}")
    if t.get("scheduled_date"):
        parts.append(f"planificada {day(t['scheduled_date'])}")
    if t.get("waiting_for"):
        follow = f", seguimiento {day(t['follow_up_date'])}" if t.get("follow_up_date") else ""
        parts.append(f"esperando a {t['waiting_for']}{follow}")
    if t.get("estimated_minutes"):
        parts.append(f"estimada {hours(t['estimated_minutes'])}")
    if t.get("is_recurring"):
        parts.append("recurrente")
    return " · ".join(parts)


def task_list(items: Iterable[dict[str, Any]], *, total: int | None = None, empty: str) -> str:
    items = list(items)
    if not items:
        return empty
    header = ""
    if total is not None and total > len(items):
        header = f"{total} tareas, se muestran {len(items)}:\n"
    return header + "\n".join(f"- {task_line(t)}" for t in items)


def task_detail(
    t: dict[str, Any], checklist: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> str:
    lines = [task_line(t)]
    if t.get("phase_name"):
        lines.append(f"Fase: {t['phase_name']}")
    if t.get("dependency_title"):
        lines.append(f"Depende de: #{t['depends_on']} {t['dependency_title']}")
    if t.get("actual_minutes"):
        lines.append(f"Tiempo registrado: {hours(t['actual_minutes'])}")
    if t.get("link_url"):
        lines.append(f"Enlace: {t['link_url']}")
    if t.get("created_by_name"):
        lines.append(f"Creada por {t['created_by_name']} el {day(t.get('created_at'))}")
    if t.get("description"):
        lines += ["", "Descripción:", t["description"].strip()]
    if checklist:
        done = sum(1 for c in checklist if c.get("is_done"))
        lines += ["", f"Checklist ({done}/{len(checklist)}):"]
        lines += [f"- [{'x' if c.get('is_done') else ' '}] {c['text']}" for c in checklist]
    if comments:
        lines += ["", f"Comentarios ({len(comments)}):"]
        lines += [
            f"- {day(c.get('created_at'))} {c.get('user_name') or 'alguien'}: {c['text']}"
            for c in comments
        ]
    return "\n".join(lines)


def project_line(p: dict[str, Any]) -> str:
    status = PROJECT_STATUS.get(p.get("status"), p.get("status"))
    parts = [f"#{p['id']} {p['name']} [{status}]"]
    if p.get("client_name"):
        parts.append(f"cliente #{p.get('client_id')} {p['client_name']}")
    if p.get("owner_name"):
        parts.append(f"responsable {p['owner_name']}")
    if p.get("task_count") is not None:
        parts.append(f"tareas {p.get('completed_task_count') or 0}/{p['task_count']}")
    if p.get("target_end_date"):
        parts.append(f"fin previsto {day(p['target_end_date'])}")
    return " · ".join(parts)


def inbox_line(n: dict[str, Any]) -> str:
    text = " ".join((n.get("raw_text") or "").split())
    if len(text) > 200:
        text = text[:200] + "…"
    parts = [f"#{n['id']} [{n.get('status')}] {text}"]
    where = " / ".join(p for p in (n.get("client_name"), n.get("project_name")) if p)
    if where:
        parts.append(where)
    parts.append(day(n.get("created_at")) or "")
    return " · ".join(p for p in parts if p)


def local_time(value: str | None, tz: tzinfo) -> str:
    """Instante ISO de la API (UTC) -> '08:42' en hora local, o con fecha si no es hoy."""
    if not value:
        return "?"
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(tz)
    if moment.date() == datetime.now(tz).date():
        return moment.strftime("%H:%M")
    return moment.strftime("%Y-%m-%d %H:%M")


def timer_line(t: dict[str, Any] | None, tz: tzinfo) -> str:
    if not t:
        return "Sin temporizador en marcha."
    state = "en pausa" if t.get("is_paused") else "en marcha"
    what = f"#{t['task_id']} {t.get('task_title')}" if t.get("task_id") else "sin tarea"
    where = f" ({t['client_name']})" if t.get("client_name") else ""
    return f"Temporizador {state} (id {t['id']}): {what}{where}, desde las {local_time(t.get('started_at'), tz)}."


DAILY_STATUS = {"draft": "borrador", "sent": "enviado"}

CLIENT_STATUS = {"act": "Actuar", "watch": "Vigilar", "ok": "Bien", "no_data": "Sin datos"}

SEO_TREND = {"up": "sube", "stable": "estable", "down": "baja", "drop_alert": "caída fuerte"}

DIGEST_STATUS = {"draft": "borrador", "reviewed": "revisado", "sent": "marcado como enviado"}

DIGEST_SIGNAL = {"ok": "al día", "due": "toca enviarlo", "late": "atrasado"}


def daily_line(d: dict[str, Any]) -> str:
    parts = [f"#{d['id']} {d.get('date')}"]
    if d.get("user_name"):
        parts.append(d["user_name"])
    parts.append(DAILY_STATUS.get(d.get("status"), d.get("status")))
    if d.get("discord_sent_at"):
        parts.append(f"en Discord {day(d['discord_sent_at'])}")
    parsed = d.get("parsed_data")
    if parsed:
        n = len(parsed.get("general") or []) + sum(len(p.get("tasks") or []) for p in parsed.get("projects") or [])
        parts.append(f"{n} punto{'s' if n != 1 else ''} en {len(parsed.get('projects') or [])} proyectos")
    else:
        parts.append("sin estructurar")
    return " · ".join(p for p in parts if p)


def _parsed_task(t: dict[str, Any]) -> str:
    details = f" — {t['details']}" if t.get("details") else ""
    return f"{t['description']}{details}"


def daily_detail(d: dict[str, Any]) -> str:
    lines = [f"Daily {daily_line(d)} (revisión {d.get('revision', 1)})"]
    parsed = d.get("parsed_data")
    if not parsed:
        text = (d.get("raw_text") or "").strip()
        lines += ["", "Texto guardado:", text or "(vacío)"]
        return "\n".join(lines)
    for project in parsed.get("projects") or []:
        where = f" ({project['client']})" if project.get("client") else ""
        lines += ["", f"{project['name']}{where}:"]
        lines += [f"- {_parsed_task(t)}" for t in project.get("tasks") or []]
    if parsed.get("general"):
        lines += ["", "General:"]
        lines += [f"- {_parsed_task(t)}" for t in parsed["general"]]
    if parsed.get("tomorrow"):
        lines += ["", "Mañana:"]
        lines += [f"- {item}" for item in parsed["tomorrow"]]
    return "\n".join(lines)


def client_status_block(s: dict[str, Any]) -> list[str]:
    """Respuesta de /api/clients/{id}/status -> líneas. Las señales a None son
    las que quien mira no puede leer: se omiten, no se inventan."""
    lines = [f"Estado: {CLIENT_STATUS.get(s.get('status'), s.get('status'))}"]
    lines += [f"- {r}" for r in s.get("reasons") or []]
    seo = s.get("seo")
    if seo:
        change = seo.get("change_pct")
        change_txt = f", {change:+.0f} %" if change is not None else ""
        trend = SEO_TREND.get(seo.get("trend"), seo.get("trend") or "sin tendencia")
        source = "Search Console" if seo.get("source") == "search_console" else "The Engine"
        as_of = f", datos hasta {day(seo['as_of'])}" if seo.get("as_of") else ""
        lines.append(f"Tráfico de Google (28 días): {seo.get('clicks')} clics frente a "
                     f"{seo.get('clicks_previous')} ({trend}{change_txt}) · {source}{as_of}")
    digest = s.get("digest")
    if digest:
        label = "mensual" if digest.get("cadence") == "monthly" else "semanal"
        last = digest.get("last_sent_period_end")
        lines.append(f"Resumen {label}: {DIGEST_SIGNAL.get(digest.get('state'), digest.get('state'))}"
                     f" · periodo esperado hasta {digest.get('expected_period_end')}"
                     + (f" · último enviado hasta {last}" if last else " · ninguno enviado"))
    tasks = s.get("tasks")
    if tasks:
        lines.append(f"Tareas: {tasks.get('overdue', 0)} vencidas · {tasks.get('waiting', 0)} esperando al cliente"
                     f" · {tasks.get('followups_late', 0)} seguimientos pasados")
    month = s.get("month")
    if month:
        line = f"Este mes: {month.get('hours')} h"
        if month.get("consumption_pct") is not None:
            line += f" · {month['consumption_pct']:.0f} % de la cuota ({month.get('fee'):.0f} €)"
        lines.append(line)
    return lines
