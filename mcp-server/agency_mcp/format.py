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
    if t.get("procedure_text") or t.get("procedure_url"):
        lines += ["", "Procedimiento:"]
        if t.get("procedure_text"):
            lines.append(t["procedure_text"].strip())
        if t.get("procedure_url"):
            lines.append(f"Documento de referencia: {t['procedure_url']}")
    if checklist:
        done = sum(1 for c in checklist if c.get("is_done"))
        lines += ["", f"Checklist ({done}/{len(checklist)}):"]
        lines += [f"- [{'x' if c.get('is_done') else ' '}] {c['text']}" for c in checklist]
    if comments:
        lines += ["", f"Comentarios ({len(comments)}):"]
        lines += [
            f"- {day(c.get('created_at'))} {c.get('user_name') or 'alguien'}"
            f"{' (borrador de IA, sin revisar)' if c.get('is_ai_draft') else ''}: {c['text']}"
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


def suggestion_line(s: dict[str, Any], tz: tzinfo, base_url: str) -> str:
    """Una sugerencia de la app: texto, quién y cuándo, desde qué página y si ya está hecha."""
    text = " ".join((s.get("text") or "").split())
    if len(text) > 400:
        text = text[:400] + "…"
    parts = [f"#{s['id']} {text}", f"{s.get('author_name') or 'alguien'}, {local_time(s.get('created_at'), tz)}"]
    if s.get("page_path"):
        parts.append(f"desde {base_url}{s['page_path']}")
    if s.get("done_at"):
        parts.append(f"hecha por {s.get('done_by_name') or '?'} ({local_time(s.get('done_at'), tz)})")
    return " · ".join(parts)


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

DIGEST_CADENCE = {"monthly": "Informe mensual", "weekly": "Seguimiento semanal"}
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
    # Una línea por cadencia encendida; ``digest`` (la peor) sólo si el backend
    # aún no manda ``digests``.
    digests = s.get("digests")
    if digests is None:
        digests = [s["digest"]] if s.get("digest") else []
    for digest in digests:
        label = DIGEST_CADENCE.get(digest.get("cadence"), "Resumen")
        last = digest.get("last_sent_period_end")
        lines.append(f"{label}: {DIGEST_SIGNAL.get(digest.get('state'), digest.get('state'))}"
                     f" · periodo esperado hasta {digest.get('expected_period_end')}"
                     + (f" · último entregado hasta {last}" if last else " · ninguno entregado"))
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
    web = web_status_line(s)
    if web:
        lines.append(web)
    return lines


# ── Webs (disponibilidad y cambios) ────────────────────────────────────

WEB_STATUS = {
    "up": "responde", "suspect": "dudosa (fallo sin confirmar)", "down": "CAÍDA",
    "blocked": "bloqueada (no nos deja comprobarla)", "unknown": "sin comprobar aún", "paused": "en pausa",
}
OUTAGE_KIND = {"down": "Caída", "blocked": "Bloqueo"}
SEVERITY = {"critical": "crítico", "warning": "aviso", "info": "menor"}
SEVERITY_PLURAL = {"critical": "críticos", "warning": "avisos", "info": "menores"}


def pct(value: float | None) -> str:
    return "sin datos" if value is None else f"{value:g} %"


def outage_line(o: dict[str, Any], tz: tzinfo) -> str:
    kind = OUTAGE_KIND.get(o.get("kind"), o.get("kind"))
    end = f"hasta {local_time(o['ended_at'], tz)}" if o.get("ended_at") else "sigue abierta"
    cause = o.get("cause_label") or o.get("cause")
    code = f" (HTTP {o['status_code']})" if o.get("status_code") else ""
    return (f"{kind} desde {local_time(o.get('started_at'), tz)}, {end} · {hours(o.get('duration_minutes'))}"
            + (f" · {cause}{code}" if cause else code))


def uptime_target_lines(t: dict[str, Any], tz: tzinfo) -> list[str]:
    name = f"{t['label']} ({t['url']})" if t.get("label") else t["url"]
    status = WEB_STATUS.get(t.get("status"), t.get("status"))
    since = ""
    if t.get("status_since") and t.get("status") != "paused":
        since = f" desde {local_time(t['status_since'], tz)}"
    line = f"- {name}: {status}{since} · 24 h {pct(t.get('uptime_24h'))} · 30 días {pct(t.get('uptime_30d'))}"
    if t.get("status") in ("down", "suspect", "blocked") and t.get("last_error_label"):
        line += f" · último error: {t['last_error_label']}"
    lines = [line]
    lines += [f"  · {outage_line(o, tz)}" for o in t.get("recent_outages") or []]
    return lines


def severity_counts(counts: dict[str, Any]) -> str:
    return " · ".join(f"{counts.get(s, 0)} {SEVERITY_PLURAL[s]}" for s in ("critical", "warning", "info"))


def web_change_line(c: dict[str, Any], tz: tzinfo, base_url: str) -> str:
    severity = SEVERITY.get(c.get("max_severity"), c.get("max_severity"))
    page = f"{c['label']} ({c['url']})" if c.get("label") else c.get("url")
    items = c.get("items") or []
    what = (items[0].get("rule_label") or items[0].get("rule_code")) if items else "cambio"
    if len(items) > 1:
        what += f" (+{len(items) - 1} más)"
    return (f"[{severity}] {what} · {page} · {local_time(c.get('detected_at'), tz)}"
            f" · {base_url}/web/cambios/{c['id']}")


def web_status_line(s: dict[str, Any]) -> str | None:
    """Bloques ``uptime`` y ``web_changes`` de /status -> una línea. None si no
    hay ninguno (sin URLs vigiladas o sin permiso de ``web``): se omite."""
    parts = []
    uptime = s.get("uptime")
    if uptime:
        n = uptime.get("targets", 0)
        status = WEB_STATUS.get(uptime.get("status"), uptime.get("status") or "sin comprobar aún")
        parts.append(f"{n} URL{'s' if n != 1 else ''} con monitor de caídas, {status}")
    changes = s.get("web_changes")
    if changes:
        parts.append(f"cambios sin revisar: {severity_counts(changes)}")
    return "Web: " + " · ".join(parts) if parts else None


GSC_METRICS = ("clicks", "impressions", "ctr", "position")


def _cell(value: Any) -> str:
    """Valor tal cual (sin redondear ni formato local); sin tabuladores ni saltos."""
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\n", " ")


def gsc_query(r: dict[str, Any]) -> str:
    """Respuesta de /gsc/query -> cabecera, totales y filas en tabla separada por tabuladores."""
    totals = r.get("totals") or {}
    out = [
        f"property: {r['property']}",
        f"start_date: {r['start_date']} · end_date: {r['end_date']} (inclusivos)",
        f"search_type: {r.get('search_type')} · data_state: {r['data_state']}"
        f" · data_available_until: {r.get('data_available_until') or 'sin datos en los últimos días'}",
        "totals (Google, sin dimensiones; incluye lo anonimizado): "
        + " · ".join(f"{m} {_cell(totals.get(m)) or '-'}" for m in GSC_METRICS),
        f"row_count: {r['row_count']} · has_more: {str(r['has_more']).lower()}"
        f" · next_start_row: {r['next_start_row'] if r.get('next_start_row') is not None else '-'}",
        "",
    ]
    dims = r.get("dimensions") or []
    if not r.get("rows"):
        out.append("(ninguna fila para ese periodo y filtros)")
        return "\n".join(out)
    out.append("\t".join([*dims, *GSC_METRICS]))
    for row in r["rows"]:
        keys = row.get("keys") or {}
        out.append("\t".join([*(_cell(keys.get(d)) for d in dims), *(_cell(row.get(m)) for m in GSC_METRICS)]))
    return "\n".join(out)


GSC_PROPERTY_ERROR = {
    "no_access": "ninguna cuenta conectada la ve",
    "reconnect_required": "la cuenta que la ve necesita reconectarse",
    "rate_limited": "Google limita las consultas ahora mismo",
    "google_error": "Google no respondió bien",
}


def gsc_properties(r: dict[str, Any]) -> str:
    out = [f"Propiedades de Search Console del cliente #{r['client_id']} {r.get('client_name')}:"]
    for p in r.get("properties") or []:
        line = (f"- {p['property']} · type: {p['type']} · is_default: {str(p['is_default']).lower()}"
                f" · permission_level: {p.get('permission_level') or '-'}"
                f" · data_available_until: {p.get('data_available_until') or '-'}")
        if p.get("error"):
            line += f" ({GSC_PROPERTY_ERROR.get(p['error'], p['error'])})"
        out.append(line)
    if r.get("reconnect_required"):
        out.append("Cuentas de Google que necesitan reconectarse (Ajustes → Search Console): "
                   + ", ".join(r["reconnect_required"]))
    return "\n".join(out)
