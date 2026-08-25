"""Daily Update Parser: uses Claude API to parse free-form daily updates
into structured data classified by project.

A team member pastes their raw daily update text and the AI extracts:
- Which projects were worked on
- What tasks were done per project
- What's planned for tomorrow
"""
from __future__ import annotations

import logging

from backend.services.ai_utils import get_anthropic_client, parse_claude_json

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
    # Presupuesto de la llamada. El cliente compartido (timeout=60, max_retries=2)
    # llega a 180 s y desborda cualquier timeout de navegador, así que aquí se
    # acota — pero acotarlo a 12 s fue pasarse de frenada: un daily real de final
    # de día tarda MÁS de eso en generarse, no en responder.
    #
    #   3 proyectos / 1,4k chars ->  7,3 s (  575 tokens de salida)
    #   5 proyectos / 2,3k chars ->  9,3 s (  878 tokens)
    #   8 proyectos / 3,6k chars -> 12,6 s (1.276 tokens)  <- ya no cabía en 12 s
    #  12 proyectos / 5,3k chars -> 20,1 s (2.076 tokens)
    #
    # Con 12 s, el recap del día entero se cortaba a media generación y el
    # reintento sólo repetía el corte: 25 s de espera para acabar sin parsear, el
    # daily guardado como "Sin parsear" y el botón de Discord devolviendo "El
    # daily no tiene datos parseados". El límite tiene que ir sobre el tiempo que
    # tarda de verdad (~20 s el peor caso medido), no por debajo.
    #
    # 40 s x 2 intentos = 80 s como mucho, dentro de los 90 s que `dailysApi` da
    # a estas llamadas (el mismo presupuesto que el resto de endpoints de IA).
    client = get_anthropic_client().with_options(timeout=40.0, max_retries=1)

    logger.info("Parsing daily update (%d chars)", len(raw_text))

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_text}],
    )

    content = parse_claude_json(message)

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
    """Format parsed daily data into a clean Discord message (one line per task)."""
    lines = []
    lines.append(f"**{user_name}** — {date_str}")
    lines.append("")

    for proj in parsed_data.get("projects", []):
        proj_name = proj.get("name") or proj.get("client") or "General"
        lines.append(f"**{proj_name}**")
        for task in proj.get("tasks", []):
            lines.append(f"✅ {task['description']}")
        lines.append("")

    if parsed_data.get("general"):
        lines.append("**General**")
        for task in parsed_data["general"]:
            lines.append(f"✅ {task['description']}")
        lines.append("")

    if parsed_data.get("tomorrow"):
        lines.append("**📅 Mañana**")
        for item in parsed_data["tomorrow"]:
            lines.append(f"• {item}")

    result = "\n".join(lines).rstrip()

    if len(result) > 2000:
        result = result[:1997] + "..."

    return result


# Magnify brand color (indigo-500)
_EMBED_COLOR = 0x6366F1


# Discord: 4096 caracteres en `description`, 2000 en `content`.
_LIMITE_DESCRIPCION = 4096
_RECORTE = "\n\n… (recortado)"


def format_raw_daily_embed(raw_text: str, user_name: str, date_str: str) -> dict:
    """Embed de reserva con el daily sin estructurar, tal cual lo escribió su autor.

    Cuando el parseo con IA falla, `parsed_data` queda a NULL. Eso bloqueaba el
    envío entero con un 400 y el informe del día no salía: el equipo se quedaba
    sin la parte que importa —lo que se hizo— por un fallo de la parte que sólo
    lo ordena. Publicar el texto en crudo dice lo mismo, sólo que sin agrupar por
    cliente.
    """
    texto = raw_text.strip()
    if len(texto) > _LIMITE_DESCRIPCION:
        texto = texto[: _LIMITE_DESCRIPCION - len(_RECORTE)] + _RECORTE

    return {
        "title": f"{user_name} — {date_str}",
        "color": _EMBED_COLOR,
        "description": texto,
        "footer": {"text": "Sin estructurar — la IA no pudo procesar este daily"},
    }


def format_daily_embed(parsed_data: dict, user_name: str, date_str: str) -> dict:
    """Format parsed daily data as a Discord rich embed dict.

    Returns a single embed dict ready to include in ``{"embeds": [embed]}``.
    Clean format: client header + ✅ per task.
    """
    fields: list[dict] = []

    for proj in parsed_data.get("projects", []):
        name = proj.get("name") or proj.get("client") or "General"
        task_lines = [f"✅ {t['description']}" for t in proj.get("tasks", [])]
        value = "\n".join(task_lines) or "—"
        fields.append({
            "name": name[:256],
            "value": value[:1024],
            "inline": False,
        })

    if parsed_data.get("general"):
        lines = [f"✅ {t['description']}" for t in parsed_data["general"]]
        fields.append({
            "name": "General",
            "value": "\n".join(lines)[:1024],
            "inline": False,
        })

    if parsed_data.get("tomorrow"):
        lines = [f"• {item}" for item in parsed_data["tomorrow"]]
        fields.append({
            "name": "📅 Mañana",
            "value": "\n".join(lines)[:1024],
            "inline": False,
        })

    embed: dict = {
        "title": f"{user_name} — {date_str}",
        "color": _EMBED_COLOR,
        "fields": fields[:25],
    }

    return embed
