"""Daily Update Parser: uses Claude API to parse free-form daily updates
into structured data classified by project.

A team member pastes their raw daily update text and the AI extracts:
- Which projects were worked on
- What tasks were done per project
- What's planned for tomorrow
"""
from __future__ import annotations

import json
import logging

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un asistente de una agencia de marketing digital (Magnify). Tu trabajo es \
parsear textos de daily updates de miembros del equipo y estructurarlos por proyecto.

Los miembros del equipo escriben sus dailys en texto libre, mencionando diferentes \
proyectos/clientes y lo que han hecho en cada uno. A veces incluyen planes para \
el dia siguiente.

REGLAS:
1. Identifica cada proyecto/cliente mencionado en el texto.
2. Clasifica cada tarea/accion bajo el proyecto correcto.
3. Si una tarea no esta claramente asociada a un proyecto, ponla en "general".
4. Extrae los planes para manana en "tomorrow" (si los hay).
5. El campo "client" del proyecto debe ser el nombre del cliente/empresa si se menciona.
6. El campo "name" del proyecto es el nombre del proyecto tal como se menciona.
7. Cada tarea tiene "description" (resumen corto, 5-15 palabras) y "details" (info adicional).
8. NO inventes informacion. Solo usa lo que dice el texto.
9. Mantén el idioma original del texto (normalmente español).
10. Responde SOLO con el JSON, sin markdown ni explicaciones.

Estructura de respuesta:
{
  "projects": [
    {
      "name": "Nombre del proyecto",
      "client": "Nombre del cliente (si se sabe)",
      "tasks": [
        {"description": "Resumen corto de la tarea", "details": "Detalles adicionales si hay"}
      ]
    }
  ],
  "general": [
    {"description": "Tarea no asociada a proyecto", "details": ""}
  ],
  "tomorrow": [
    "Tarea planificada para mañana"
  ]
}"""


async def parse_daily_update(raw_text: str) -> dict:
    """Call Claude API to parse a raw daily update into structured data.

    Returns the parsed dict with projects, general tasks, and tomorrow plans.
    Raises ValueError if API key is missing or response is invalid.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no configurada. Agrega la clave en el archivo .env"
        )

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    logger.info("Parsing daily update (%d chars)", len(raw_text))

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_text}],
    )

    raw_response = message.content[0].text.strip()

    # Clean potential markdown wrapping
    if raw_response.startswith("```"):
        lines = raw_response.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_response = "\n".join(lines)

    try:
        content = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude response as JSON: %s", raw_response[:200])
        raise ValueError(f"La respuesta de Claude no es JSON valido: {e}") from e

    # Validate and normalize structure
    result = {
        "projects": [],
        "general": [],
        "tomorrow": [],
    }

    for proj in content.get("projects", []):
        if not isinstance(proj, dict) or "name" not in proj:
            continue
        tasks = []
        for t in proj.get("tasks", []):
            if isinstance(t, dict) and "description" in t:
                tasks.append({
                    "description": t["description"],
                    "details": t.get("details", ""),
                })
        result["projects"].append({
            "name": proj["name"],
            "client": proj.get("client", ""),
            "tasks": tasks,
        })

    for t in content.get("general", []):
        if isinstance(t, dict) and "description" in t:
            result["general"].append({
                "description": t["description"],
                "details": t.get("details", ""),
            })

    for item in content.get("tomorrow", []):
        if isinstance(item, str):
            result["tomorrow"].append(item)

    total_tasks = sum(len(p["tasks"]) for p in result["projects"]) + len(result["general"])
    logger.info(
        "Daily parsed: %d projects, %d total tasks, %d tomorrow items",
        len(result["projects"]),
        total_tasks,
        len(result["tomorrow"]),
    )

    return result


def format_daily_for_discord(parsed_data: dict, user_name: str, date_str: str) -> str:
    """Format parsed daily data into a Discord-friendly message."""
    lines = []
    lines.append(f"📋 **Daily Update — {user_name}** ({date_str})")
    lines.append("")

    for proj in parsed_data.get("projects", []):
        client_tag = f" ({proj['client']})" if proj.get("client") else ""
        lines.append(f"**🔹 {proj['name']}{client_tag}**")
        for task in proj.get("tasks", []):
            lines.append(f"  • {task['description']}")
            if task.get("details"):
                lines.append(f"    ↳ {task['details'][:150]}")
        lines.append("")

    if parsed_data.get("general"):
        lines.append("**🔸 General**")
        for task in parsed_data["general"]:
            lines.append(f"  • {task['description']}")
        lines.append("")

    if parsed_data.get("tomorrow"):
        lines.append("**📅 Mañana**")
        for item in parsed_data["tomorrow"]:
            lines.append(f"  • {item}")

    result = "\n".join(lines)

    # Discord limit
    if len(result) > 2000:
        result = result[:1997] + "..."

    return result
