"""Digest Generator: uses Claude API to transform raw data into client-facing digest content.

Receives collector data + tone setting, calls Claude API, and returns
structured JSON content ready for the WeeklyDigest model.
"""

from __future__ import annotations

import asyncio
import logging

from backend.db.models import DigestTone
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)


class DigestProviderError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# Tone descriptions for the prompt
TONE_INSTRUCTIONS = {
    DigestTone.formal: (
        "Tono formal y profesional. Usa usted. "
        "Frases completas y estructuradas. Sin emojis ni coloquialismos."
    ),
    DigestTone.cercano: (
        "Tono cercano y amigable pero profesional. Tutea al cliente. "
        "Puedes usar algun emoji sutil. Frases directas y claras."
    ),
    DigestTone.equipo: (
        "Tono de equipo interno, relajado y directo. "
        "Usa lenguaje informal, emojis, y abreviaciones si quedan bien."
    ),
}

SYSTEM_PROMPT = """\
Eres un asistente de una agencia de marketing digital (Magnify) que redacta \
resúmenes semanales (digests) para clientes. Tu trabajo es transformar datos \
técnicos internos en un resumen claro, conciso y orientado al cliente.

REGLAS:
1. El digest tiene 4 partes: greeting, date, sections (done/need/next/metrics), closing.
2. Cada sección tiene items con title (corto, 5-10 palabras) y description (1-2 frases).
3. "done" = lo que se completó esta semana. Celebra logros sin exagerar.
4. "need" = lo que necesita atención del cliente (aprobaciones, feedback, accesos, contenido).
5. "next" = próximos pasos planificados para la semana siguiente.
6. "metrics" = métricas clave de la semana (horas invertidas, progreso, KPIs si hay datos). Máximo 2-3 items.
7. NO inventes datos. Solo usa la información proporcionada.
8. Si no hay items para una sección, déjala vacía ([]).
8. El greeting DEBE tener este formato exacto: "Hola [nombre del contacto/cliente] 👋,\nAquí tienes el resumen de esta semana para [nombre del proyecto, los proyectos o el cliente]". Incluye salto de línea y refleja todos los proyectos presentes en los datos.
9. La date DEBE tener este formato exacto: "Te enviamos el informe semanal del [día inicio] al [día final] de [mes] [año]". Ejemplo: "Te enviamos el informe semanal del 10 al 17 de marzo 2026".
10. El closing debe ser breve y motivador, acorde al tono.
11. Responde SOLO con el JSON, sin markdown ni explicaciones."""

USER_PROMPT_TEMPLATE = """\
Genera el digest semanal con estos datos:

CLIENTE: {client_name}
PROYECTO: {project_name}
PROGRESO DEL PROYECTO: {project_progress}%
PERIODO: {period_start} al {period_end}

TONO: {tone_instruction}

--- TAREAS COMPLETADAS ({completed_count}) ---
{completed_tasks}

--- TAREAS EN CURSO ({in_progress_count}) ---
{in_progress_tasks}

--- TAREAS PENDIENTES ({pending_count}) ---
{pending_tasks}

--- HORAS INVERTIDAS ---
Total: {total_hours}h ({total_minutes} minutos)

--- SEGUIMIENTOS PENDIENTES ({followup_count}) ---
{followups}

Responde con un JSON con esta estructura exacta:
{{
  "greeting": "...",
  "date": "Semana del ... al ... de ... ...",
  "sections": {{
    "done": [{{"title": "...", "description": "..."}}],
    "need": [{{"title": "...", "description": "..."}}],
    "next": [{{"title": "...", "description": "..."}}],
    "metrics": [{{"title": "...", "description": "..."}}]
  }},
  "closing": "..."
}}"""

GROUPED_USER_PROMPT_TEMPLATE = """\
Genera el digest semanal con estos datos. Los totales son completos; las listas
marcadas como muestra pueden contener solo los primeros elementos.

CLIENTE: {client_name}
PERIODO: {period_start} al {period_end}
TONO: {tone_instruction}

--- TOTALES DEL CONTEXTO INCLUIDO ---
Incluyen proyectos actuales y proyectos históricos con hechos en el periodo;
omiten proyectos históricos sin hechos en el periodo.
Proyectos: {project_count}
Referencias de proyecto no resueltas: {unresolved_project_count}
Tareas completadas en el periodo: {completed_total}
Tareas en curso: {in_progress_total}
Tareas pendientes: {pending_total}
Horas invertidas: {total_hours}h ({total_minutes} minutos)

--- HECHOS POR PROYECTO ---
{project_sections}

--- SEGUIMIENTOS PENDIENTES ({followup_count}) ---
{followups}

No atribuyas un hecho de un proyecto a otro. Los hechos bajo "Sin proyecto"
son del cliente, pero no pertenecen a ningún proyecto.

Responde con un JSON con esta estructura exacta:
{{
  "greeting": "...",
  "date": "Semana del ... al ... de ... ...",
  "sections": {{
    "done": [{{"title": "...", "description": "..."}}],
    "need": [{{"title": "...", "description": "..."}}],
    "next": [{{"title": "...", "description": "..."}}],
    "metrics": [{{"title": "...", "description": "..."}}]
  }},
  "closing": "..."
}}"""


def _format_task_list(tasks: list[dict]) -> str:
    """Format a list of task dicts for the prompt."""
    if not tasks:
        return "(ninguna)"
    lines = []
    for t in tasks:
        line = f"- {t['title']}"
        if t.get("description"):
            line += f": {t['description'][:120]}"
        if t.get("assigned_to"):
            line += f" [Asignado: {t['assigned_to']}]"
        if t.get("due_date"):
            line += f" [Fecha: {t['due_date']}]"
        if t.get("estimated_minutes") and t.get("actual_minutes"):
            line += (
                f" [Est: {t['estimated_minutes']}min / Real: {t['actual_minutes']}min]"
            )
        lines.append(line)
    return "\n".join(lines)


def _format_followups(followups: list[dict]) -> str:
    """Format followup items for the prompt."""
    if not followups:
        return "(ninguno)"
    lines = []
    for f in followups:
        line = f"- {f.get('subject') or 'Sin asunto'}"
        if f.get("summary"):
            line += f": {f['summary'][:120]}"
        if f.get("contact_name"):
            line += f" [Contacto: {f['contact_name']}]"
        if f.get("followup_date"):
            line += f" [Fecha: {f['followup_date']}]"
        lines.append(line)
    return "\n".join(lines)


def _format_project_group(group: dict) -> str:
    name = group.get("project_name") or "Sin proyecto"
    project_id = group.get("project_id")
    identity = f"{name} (ID {project_id})" if project_id is not None else name
    progress = group.get("progress_percent")
    progress_line = f"Progreso actual: {progress}%\n" if progress is not None else ""
    return (
        f"### {identity}\n"
        f"{progress_line}"
        f"Tareas totales actuales: {group.get('task_total', 0)}\n"
        f"Completadas en el periodo: {group.get('completed_total', 0)} "
        f"(muestra {len(group.get('completed_tasks', []))})\n"
        f"{_format_task_list(group.get('completed_tasks', []))}\n"
        f"En curso: {group.get('in_progress_total', 0)} "
        f"(muestra {len(group.get('in_progress_tasks', []))})\n"
        f"{_format_task_list(group.get('in_progress_tasks', []))}\n"
        f"Pendientes: {group.get('pending_total', 0)} "
        f"(muestra {len(group.get('pending_tasks', []))})\n"
        f"{_format_task_list(group.get('pending_tasks', []))}\n"
        f"Tiempo del periodo: {group.get('total_hours', 0)}h "
        f"({group.get('total_minutes', 0)} minutos)"
        + (
            f" [incluye {group.get('historical_template_minutes')} minutos reales "
            "registrados sobre plantillas históricas]"
            if group.get("historical_template_minutes")
            else ""
        )
    )


def _build_user_prompt(raw_data: dict, tone: DigestTone) -> str:
    """Build the user prompt from collector data."""
    if raw_data.get("context_version") == 2 and "projects" in raw_data:
        groups = list(raw_data.get("projects", []))
        groups.extend(raw_data.get("unresolved_projects", []))
        unassigned = raw_data.get("unassigned")
        if unassigned and any(
            unassigned.get(key, 0)
            for key in (
                "task_total",
                "completed_total",
                "in_progress_total",
                "pending_total",
                "total_minutes",
            )
        ):
            groups.append(unassigned)
        totals = raw_data.get("totals", {})
        return GROUPED_USER_PROMPT_TEMPLATE.format(
            client_name=raw_data.get("client_name", "Cliente"),
            period_start=raw_data.get("period_start", ""),
            period_end=raw_data.get("period_end", ""),
            tone_instruction=TONE_INSTRUCTIONS[tone],
            project_count=totals.get(
                "project_count", len(raw_data.get("projects", []))
            ),
            unresolved_project_count=totals.get(
                "unresolved_project_count",
                len(raw_data.get("unresolved_projects", [])),
            ),
            completed_total=totals.get("completed_total", 0),
            in_progress_total=totals.get("in_progress_total", 0),
            pending_total=totals.get("pending_total", 0),
            total_hours=totals.get("total_hours", raw_data.get("total_hours", 0)),
            total_minutes=totals.get("total_minutes", raw_data.get("total_minutes", 0)),
            project_sections="\n\n".join(
                _format_project_group(group) for group in groups
            )
            or "(sin proyectos ni tareas)",
            followup_count=len(raw_data.get("pending_followups", [])),
            followups=_format_followups(raw_data.get("pending_followups", [])),
        )
    return USER_PROMPT_TEMPLATE.format(
        client_name=raw_data.get("client_name", "Cliente"),
        project_name=raw_data.get("project_name") or "Sin proyecto",
        project_progress=raw_data.get("project_progress") or 0,
        period_start=raw_data.get("period_start", ""),
        period_end=raw_data.get("period_end", ""),
        tone_instruction=TONE_INSTRUCTIONS[tone],
        completed_count=len(raw_data.get("completed_tasks", [])),
        completed_tasks=_format_task_list(raw_data.get("completed_tasks", [])),
        in_progress_count=len(raw_data.get("in_progress_tasks", [])),
        in_progress_tasks=_format_task_list(raw_data.get("in_progress_tasks", [])),
        pending_count=len(raw_data.get("pending_tasks", [])),
        pending_tasks=_format_task_list(raw_data.get("pending_tasks", [])),
        total_hours=raw_data.get("total_hours", 0),
        total_minutes=raw_data.get("total_minutes", 0),
        followup_count=len(raw_data.get("pending_followups", [])),
        followups=_format_followups(raw_data.get("pending_followups", [])),
    )


SOURCE_RULES = """Cada item debe incluir source_keys (1-8 claves únicas) tomadas
literalmente del CATÁLOGO DE FUENTES. done usa task_completed; need usa followup
o task_active; next usa task_active, project o period; metrics usa aggregate.
Las claves prueban los hechos consultados, no certifican interpretaciones libres."""


def _with_source_contract(prompt: str, raw_data: dict) -> str:
    catalog = raw_data.get("source_catalog") or {}
    rendered = "\n".join(
        f"- {key} [{value.get('class', 'unknown')}]"
        for key, value in sorted(catalog.items())
    )
    return f"{prompt}\n\n{SOURCE_RULES}\nCATÁLOGO DE FUENTES:\n{rendered or '(vacío)'}"


def _validate_sources(result: dict, raw_data: dict) -> dict:
    catalog = raw_data.get("source_catalog") or {}
    allowed_classes = {
        "done": {"task_completed", "legacy"},
        "need": {"followup", "task_active", "legacy"},
        "next": {"task_active", "project", "period", "legacy"},
        "metrics": {"aggregate", "legacy"},
    }
    for section, items in result["sections"].items():
        for item in items:
            keys = item.get("source_keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 8:
                raise ValueError(
                    "Cada afirmación generada necesita entre 1 y 8 fuentes"
                )
            if any(not isinstance(key, str) for key in keys) or len(keys) != len(
                set(keys)
            ):
                raise ValueError(
                    "Las fuentes de una afirmación deben ser claves únicas"
                )
            if any(key not in catalog for key in keys):
                raise ValueError("La respuesta contiene una fuente desconocida")
            if any(
                catalog[key].get("class") not in allowed_classes[section]
                for key in keys
            ):
                raise ValueError("La fuente no corresponde a la sección indicada")
    return result


async def generate_digest_content(
    raw_data: dict,
    tone: DigestTone = DigestTone.cercano,
) -> dict:
    """Call Claude API to generate digest content from raw collector data.

    Returns the parsed DigestContent dict:
    {greeting, date, sections: {done, need, next}, closing}

    Raises DigestProviderError for provider availability/timeouts and ValueError
    for invalid generated content.
    """
    try:
        client = get_anthropic_client().with_options(timeout=35.0, max_retries=0)
    except ValueError as exc:
        raise DigestProviderError("provider_unavailable") from exc

    user_prompt = _with_source_contract(_build_user_prompt(raw_data, tone), raw_data)

    logger.info(
        "Generating digest for client=%s tone=%s",
        raw_data.get("client_name"),
        tone.value,
    )

    try:
        async with asyncio.timeout(45):
            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
    except TimeoutError as exc:
        raise DigestProviderError("provider_timeout") from exc

    content = parse_claude_json(message)

    # Validate minimal structure
    if "sections" not in content:
        raise ValueError("La respuesta no contiene 'sections'")

    # Ensure all required keys exist with defaults
    result = {
        "greeting": content.get("greeting", ""),
        "date": content.get("date", ""),
        "sections": {
            "done": content.get("sections", {}).get("done", []),
            "need": content.get("sections", {}).get("need", []),
            "next": content.get("sections", {}).get("next", []),
            "metrics": content.get("sections", {}).get("metrics", []),
        },
        "closing": content.get("closing", ""),
    }

    # Validate items have title+description
    for section_name in ("done", "need", "next", "metrics"):
        items = result["sections"][section_name]
        validated = []
        for item in items:
            if isinstance(item, dict) and "title" in item:
                validated.append(
                    {
                        "title": item["title"],
                        "description": item.get("description", ""),
                        "source_keys": item.get("source_keys"),
                    }
                )
        result["sections"][section_name] = validated

    logger.info(
        "Digest generated: done=%d, need=%d, next=%d, metrics=%d",
        len(result["sections"]["done"]),
        len(result["sections"]["need"]),
        len(result["sections"]["next"]),
        len(result["sections"]["metrics"]),
    )

    return _validate_sources(result, raw_data)
