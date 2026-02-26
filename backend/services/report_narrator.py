"""Report Narrator: uses Claude API to transform rule-based report sections
into polished, narrative-style reports ready to share with clients.
"""
from __future__ import annotations

import json
import logging

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un redactor profesional de informes para una agencia de marketing digital (Magnify). \
Tu trabajo es transformar datos estructurados de informes internos en narrativas claras, \
profesionales y orientadas al cliente.

REGLAS:
1. Escribe en español, tono profesional pero cercano (tutea al cliente).
2. Transforma los datos fríos en párrafos que cuenten una historia coherente.
3. Destaca logros y progreso de forma positiva pero honesta.
4. Si hay problemas o retrasos, mencionarlos con tacto y enfocados en la solución.
5. NO inventes datos. Solo usa la información proporcionada.
6. Estructura la respuesta en secciones con títulos.
7. Cada sección debe ser un párrafo fluido, NO una lista de bullets (a menos que sea necesario para claridad).
8. Incluye una introducción y un cierre motivador.
9. Si hay datos de horas/tareas, contextualiza para que el cliente entienda el valor.
10. Responde SOLO con el JSON, sin markdown ni explicaciones.

Responde con un JSON así:
{
  "narrative": "El texto completo del informe narrativo en formato markdown",
  "executive_summary": "Un párrafo de 2-3 frases con lo más importante"
}"""


async def generate_report_narrative(
    report_title: str,
    sections: list[dict],
    summary: str,
    client_name: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Call Claude API to generate a narrative from report sections.

    Returns dict with 'narrative' (full text) and 'executive_summary' (brief).
    Raises ValueError if API key is missing or response is invalid.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no configurada. Agrega la clave en el archivo .env"
        )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build the user prompt from sections
    context_parts = []
    if client_name:
        context_parts.append(f"CLIENTE: {client_name}")
    if project_name:
        context_parts.append(f"PROYECTO: {project_name}")
    context_parts.append(f"TÍTULO DEL INFORME: {report_title}")
    context_parts.append("")

    for section in sections:
        context_parts.append(f"--- {section.get('title', 'Sección')} ---")
        context_parts.append(section.get("content", ""))
        context_parts.append("")

    user_prompt = (
        "Transforma este informe estructurado en una narrativa profesional:\n\n"
        + "\n".join(context_parts)
    )

    logger.info("Generating AI narrative for report: %s", report_title)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()

    # Clean markdown wrapping
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    try:
        content = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse narrative response: %s", raw_text[:200])
        raise ValueError(f"La respuesta de Claude no es JSON válido: {e}") from e

    result = {
        "narrative": content.get("narrative", ""),
        "executive_summary": content.get("executive_summary", ""),
    }

    if not result["narrative"]:
        raise ValueError("La narrativa generada está vacía")

    logger.info("Narrative generated: %d chars", len(result["narrative"]))

    return result
