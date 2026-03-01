"""Report Narrator: uses Claude API to transform rule-based report sections
into polished, SCQA-structured narrative reports ready to share with clients.
"""
from __future__ import annotations

import logging

from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)

AUDIENCE_ADDENDUMS = {
    "executive": (
        "\nAUDIENCIA: Ejecutivos / Directivos.\n"
        "- Alto nivel, enfocado en ROI, progreso general y decisiones estratégicas.\n"
        "- Máximo 1 página equivalente. Sin detalles operativos ni técnicos.\n"
        "- Prioriza métricas de impacto de negocio."
    ),
    "marketing": (
        "\nAUDIENCIA: Equipo de Marketing.\n"
        "- Métricas detalladas, tendencias, comparativas con períodos anteriores.\n"
        "- Nivel medio de detalle técnico. Incluye datos de tráfico, conversiones, SEO.\n"
        "- Destaca oportunidades de optimización."
    ),
    "operational": (
        "\nAUDIENCIA: Equipo Operativo / Gestión de Proyectos.\n"
        "- Máximo detalle: tareas, timelines, blockers, asignaciones.\n"
        "- Incluye estado de cada fase y próximos pasos concretos con responsables.\n"
        "- Destaca riesgos y dependencias."
    ),
}


def _build_system_prompt(audience: str | None = None) -> str:
    """Build the system prompt, optionally tailored for a specific audience."""
    base = """\
Eres un redactor profesional de informes para una agencia de marketing digital (Magnify). \
Tu trabajo es transformar datos estructurados de informes internos en narrativas claras, \
profesionales y orientadas al cliente.

REGLAS:
1. Escribe en español, tono profesional pero cercano (tutea al cliente).
2. Transforma los datos fríos en párrafos que cuenten una historia coherente.
3. Destaca logros y progreso de forma positiva pero honesta.
4. Si hay problemas o retrasos, mencionarlos con tacto y enfocados en la solución.
5. NO inventes datos. Solo usa la información proporcionada.
6. Cada sección debe ser un párrafo fluido, NO una lista de bullets (a menos que sea necesario para claridad).
7. Incluye una introducción y un cierre motivador.
8. Si hay datos de horas/tareas, contextualiza para que el cliente entienda el valor.
9. Responde SOLO con el JSON, sin markdown ni explicaciones.

ESTRUCTURA (Framework SCQA):
1. RESUMEN EJECUTIVO: 3-5 líneas con lo más importante del período.
2. SITUACIÓN: Contexto actual, métricas clave, logros del período.
3. COMPLICACIÓN: Desafíos encontrados, alertas, retrasos (si los hay). Si no hay complicaciones relevantes, indica brevemente que el período transcurrió sin incidencias significativas.
4. RESPUESTA: Acciones tomadas, resultados obtenidos, cómo se abordaron los retos.
5. PRÓXIMOS PASOS: Acciones concretas planificadas para el siguiente período.

Responde con un JSON así:
{
  "executive_summary": "Párrafo de 2-3 frases con lo más importante",
  "narrative": "Texto completo del informe narrativo en formato markdown con la estructura SCQA",
  "scqa_sections": [
    {"key": "situation", "title": "Situación", "content": "..."},
    {"key": "complication", "title": "Complicación", "content": "..."},
    {"key": "answer", "title": "Respuesta", "content": "..."},
    {"key": "next_steps", "title": "Próximos Pasos", "content": "..."}
  ]
}"""

    if audience and audience in AUDIENCE_ADDENDUMS:
        base += AUDIENCE_ADDENDUMS[audience]

    return base


async def generate_report_narrative(
    report_title: str,
    sections: list[dict],
    summary: str,
    client_name: str | None = None,
    project_name: str | None = None,
    audience: str | None = None,
) -> dict:
    """Call Claude API to generate a SCQA narrative from report sections.

    Returns dict with 'narrative', 'executive_summary', and 'scqa_sections'.
    Raises ValueError if API key is missing or response is invalid.
    """
    client = get_anthropic_client()

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
        "Transforma este informe estructurado en una narrativa profesional con estructura SCQA:\n\n"
        + "\n".join(context_parts)
    )

    logger.info("Generating AI narrative for report: %s (audience=%s)", report_title, audience)

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=_build_system_prompt(audience),
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = parse_claude_json(message)

    result = {
        "narrative": content.get("narrative", ""),
        "executive_summary": content.get("executive_summary", ""),
        "scqa_sections": content.get("scqa_sections", []),
    }

    if not result["narrative"]:
        raise ValueError("La narrativa generada está vacía")

    logger.info("Narrative generated: %d chars, %d SCQA sections",
                len(result["narrative"]), len(result["scqa_sections"]))

    return result
