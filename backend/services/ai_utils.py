"""Shared utilities for Claude AI services: client singleton + JSON parsing."""
from __future__ import annotations

import json
import logging

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    """Return a shared AsyncAnthropic client (lazy singleton).

    Raises ValueError if ANTHROPIC_API_KEY is not configured.
    """
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY no configurada. Agrega la clave en el archivo .env"
            )
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def parse_claude_json(message: anthropic.types.Message) -> dict:
    """Extract and parse JSON from a Claude API response.

    Strips markdown code fences (```json ... ```) if present and parses
    the resulting text as JSON.

    Raises ValueError if the response cannot be parsed.
    """
    if not message.content:
        raise ValueError("Claude returned an empty response")
    raw_text = message.content[0].text.strip()

    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude JSON response: %s", raw_text[:200])
        raise ValueError(f"La respuesta de Claude no es JSON valido: {e}") from e
