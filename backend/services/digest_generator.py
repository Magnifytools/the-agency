"""Digest Generator: uses Claude API to transform raw data into client-facing digest content.

Receives collector data + tone setting, calls Claude API, and returns
structured JSON content ready for the WeeklyDigest model.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic

from backend.config import settings
from backend.db.models import DigestTone

logger = logging.getLogger(__name__)

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
1. El digest tiene 4 partes: greeting, date, sections (done/need/next), closing.
2. Cada sección tiene items con title (corto, 5-10 palabras) y description (1-2 frases).
3. "done" = lo que se completó esta semana. Celebra logros sin exagerar.
4. "need" = lo que necesita atención del cliente (aprobaciones, feedback, accesos, contenido).
5. "next" = próximos pasos planificados para la semana siguiente.
6. NO inventes datos. Solo usa la información proporcionada.
7. Si no hay items para una sección, déjala vacía ([]).
8. El greeting debe incluir el nombre del cliente.
9. La date debe ser legible: "Semana del X al Y de mes año".
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
    "next": [{{"title": "...", "description": "..."}}]
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
            line += f" [Est: {t['estimated_minutes']}min / Real: {t['actual_minutes']}min]"
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


def _build_user_prompt(raw_data: dict, tone: DigestTone) -> str:
    """Build the user prompt from collector data."""
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


async def generate_digest_content(
    raw_data: dict,
    tone: DigestTone = DigestTone.cercano,
) -> dict:
    """Call Claude API to generate digest content from raw collector data.

    Returns the parsed DigestContent dict:
    {greeting, date, sections: {done, need, next}, closing}

    Raises ValueError if API key is missing or response is invalid.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no configurada. Agrega la clave en el archivo .env"
        )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_prompt = _build_user_prompt(raw_data, tone)

    logger.info(
        "Generating digest for client=%s tone=%s",
        raw_data.get("client_name"),
        tone.value,
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract the text content
    raw_text = message.content[0].text.strip()

    # Clean potential markdown wrapping
    if raw_text.startswith("```"):
        # Remove ```json ... ``` wrapper
        lines = raw_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    try:
        content = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text[:200])
        raise ValueError(f"La respuesta de Claude no es JSON valido: {e}") from e

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
        },
        "closing": content.get("closing", ""),
    }

    # Validate items have title+description
    for section_name in ("done", "need", "next"):
        items = result["sections"][section_name]
        validated = []
        for item in items:
            if isinstance(item, dict) and "title" in item:
                validated.append({
                    "title": item["title"],
                    "description": item.get("description", ""),
                })
        result["sections"][section_name] = validated

    logger.info(
        "Digest generated: done=%d, need=%d, next=%d",
        len(result["sections"]["done"]),
        len(result["sections"]["need"]),
        len(result["sections"]["next"]),
    )

    return result
