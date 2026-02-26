"""Email Drafter: uses Claude API to draft professional emails
for client communications, with context from recent interactions.
"""
from __future__ import annotations

import json
import logging

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un asistente de redaccion de emails para una agencia de marketing digital (Magnify). \
Tu trabajo es redactar emails profesionales dirigidos a clientes o en respuesta \
a comunicaciones previas.

REGLAS:
1. Escribe en espanol, tono profesional pero cercano (tutea al cliente).
2. El email debe ser claro, conciso y orientado a la accion.
3. Si se proporciona contexto de comunicaciones previas, mantenlo coherente.
4. Si es una respuesta, referencia naturalmente el tema previo.
5. NO inventes datos concretos (cifras, fechas, nombres) que no esten en el contexto.
6. Si faltan datos, usa placeholders claros como [DATO], [FECHA], etc.
7. Adapta la longitud al proposito: breve para confirmaciones, mas detallado para propuestas.
8. Incluye un saludo y una despedida profesional.
9. Si hay tareas pendientes o followups, mencionalos de forma proactiva.
10. Responde SOLO con el JSON, sin markdown ni explicaciones.

Responde con un JSON asi:
{
  "subject": "Asunto del email (corto y descriptivo)",
  "body": "El cuerpo completo del email, con saludo y despedida",
  "tone": "profesional|cercano|formal",
  "suggested_followup": "Sugerencia de followup si aplica, o null"
}"""


async def draft_email(
    client_name: str,
    contact_name: str | None = None,
    purpose: str = "",
    reply_to: dict | None = None,
    recent_communications: list[dict] | None = None,
    project_context: str | None = None,
) -> dict:
    """Call Claude API to draft an email for a client communication.

    Args:
        client_name: Name of the client company.
        contact_name: Name of the specific contact person.
        purpose: What the email should accomplish (e.g., "seguimiento proyecto", "enviar propuesta").
        reply_to: Previous communication dict to reply to (subject, summary, contact_name).
        recent_communications: List of recent communication dicts for context.
        project_context: Optional project status context string.

    Returns dict with 'subject', 'body', 'tone', 'suggested_followup'.
    Raises ValueError if API key is missing or response is invalid.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no configurada. Agrega la clave en el archivo .env"
        )

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build context parts
    context_parts = [f"CLIENTE: {client_name}"]
    if contact_name:
        context_parts.append(f"CONTACTO: {contact_name}")
    context_parts.append(f"PROPOSITO: {purpose}")
    context_parts.append("")

    # Add reply context
    if reply_to:
        context_parts.append("--- EMAIL/COMUNICACION A RESPONDER ---")
        if reply_to.get("subject"):
            context_parts.append(f"Asunto: {reply_to['subject']}")
        if reply_to.get("summary"):
            context_parts.append(f"Resumen: {reply_to['summary']}")
        if reply_to.get("contact_name"):
            context_parts.append(f"De: {reply_to['contact_name']}")
        if reply_to.get("channel"):
            context_parts.append(f"Canal: {reply_to['channel']}")
        context_parts.append("")

    # Add recent communications context
    if recent_communications:
        context_parts.append(
            f"--- COMUNICACIONES RECIENTES ({len(recent_communications)}) ---"
        )
        for comm in recent_communications[:5]:  # Limit to 5 most recent
            direction = "Entrante" if comm.get("direction") == "inbound" else "Saliente"
            context_parts.append(
                f"- [{direction}] {comm.get('subject') or 'Sin asunto'}: "
                f"{(comm.get('summary') or '')[:150]}"
            )
        context_parts.append("")

    # Add project context
    if project_context:
        context_parts.append("--- CONTEXTO DEL PROYECTO ---")
        context_parts.append(project_context)
        context_parts.append("")

    user_prompt = (
        "Redacta un email profesional con este contexto:\n\n"
        + "\n".join(context_parts)
    )

    logger.info("Drafting email for client: %s, purpose: %s", client_name, purpose)

    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
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
        logger.error("Failed to parse email draft response: %s", raw_text[:200])
        raise ValueError(f"La respuesta de Claude no es JSON valido: {e}") from e

    result = {
        "subject": content.get("subject", ""),
        "body": content.get("body", ""),
        "tone": content.get("tone", "profesional"),
        "suggested_followup": content.get("suggested_followup"),
    }

    if not result["body"]:
        raise ValueError("El borrador de email esta vacio")

    logger.info("Email draft generated: %d chars", len(result["body"]))

    return result
