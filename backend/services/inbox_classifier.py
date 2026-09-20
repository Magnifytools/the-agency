"""AI-powered classification for inbox notes using Claude."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.services.ai_utils import get_anthropic_client

class InboxProviderUnavailable(RuntimeError):
    """Sanitized boundary error for provider setup or transport failures."""


class SuggestedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictInt | None = None
    name: str = Field(default="", max_length=200)
    confidence: float = Field(ge=0, le=1, strict=True, allow_inf_nan=False)


class InboxClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_project: SuggestedEntity | None
    suggested_client: SuggestedEntity | None
    suggested_action: Literal["create_task", "add_communication", "link_to_project"]
    suggested_title: str = Field(max_length=200)
    suggested_priority: Literal["low", "medium", "high", "urgent"]
    reasoning: str = Field(max_length=500)


def _parse_provider_json(message) -> dict:
    """Parse the provider response without logging user or provider text."""
    if getattr(message, "stop_reason", None) == "refusal" or not message.content:
        raise ValueError("Invalid provider response")
    first = message.content[0]
    if getattr(first, "type", None) != "text" or not getattr(first, "text", None):
        raise ValueError("Invalid provider response")
    raw = first.text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        raw = "\n".join(lines)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Invalid provider response") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Invalid provider response")
    return parsed

SYSTEM_PROMPT = """\
Eres un asistente de una agencia de marketing digital (Magnify). Tu trabajo es \
clasificar notas rapidas del inbox de un miembro del equipo.

Se te dara:
1. La nota del usuario (texto libre)
2. Lista de proyectos activos con su cliente
3. Lista de clientes activos

REGLAS:
1. Sugiere el proyecto mas probable al que pertenece la nota.
2. Si no hay un proyecto claro, sugiere al menos el cliente.
3. Sugiere una accion: "create_task" (crear tarea), "add_communication" (registrar comunicacion), \
o "link_to_project" (asociar al proyecto sin crear tarea).
4. Sugiere un titulo corto (5-15 palabras) para la tarea si aplica.
5. Sugiere prioridad: "low", "medium", "high", "urgent".
6. Incluye un "reasoning" breve explicando tu decision.
7. Los campos de confidence van de 0.0 a 1.0.
8. Si no hay suficiente informacion, usa confidence baja (< 0.5).
9. Responde SOLO con el JSON, sin markdown ni explicaciones.
10. Manten el idioma original del texto.

Estructura de respuesta:
{
  "suggested_project": {"id": <int|null>, "name": "<string>", "confidence": <float>},
  "suggested_client": {"id": <int|null>, "name": "<string>", "confidence": <float>},
  "suggested_action": "<create_task|add_communication|link_to_project>",
  "suggested_title": "<string>",
  "suggested_priority": "<low|medium|high|urgent>",
  "reasoning": "<string>"
}"""


async def classify_inbox_note(
    raw_text: str,
    projects: list[dict],
    clients: list[dict],
) -> dict:
    """Classify an inbox note using Claude AI.

    Args:
        raw_text: The note text to classify.
        projects: List of active projects with keys: id, name, client_name.
        clients: List of active clients with keys: id, name.

    Returns:
        Parsed JSON dict with classification suggestion.
    """
    try:
        client = get_anthropic_client()
    except Exception as exc:
        raise InboxProviderUnavailable() from exc

    context = "PROYECTOS ACTIVOS:\n"
    for p in projects:
        context += f"- ID:{p['id']} \"{p['name']}\" (cliente: {p['client_name']})\n"
    context += "\nCLIENTES ACTIVOS:\n"
    for c in clients:
        context += f"- ID:{c['id']} \"{c['name']}\"\n"
    context += f"\n<user_note>\n{raw_text}\n</user_note>"

    try:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
    except Exception as exc:
        raise InboxProviderUnavailable() from exc

    parsed = _parse_provider_json(message)
    return InboxClassification.model_validate(parsed).model_dump()
