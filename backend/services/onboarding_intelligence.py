"""Client Onboarding Intelligence: generates an AI analysis of a new client's business."""
from __future__ import annotations

import logging
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un analista de negocio digital experto en SEO y marketing.
Recibirás la URL del sitio web de un cliente y opcionalmente información adicional.
Genera un informe de inteligencia estructurado en JSON con este formato exacto:

{
  "business_summary": "Resumen del negocio en 2-3 frases (qué hacen, target, modelo de negocio)",
  "industry": "Sector/industria principal",
  "target_audience": "Descripción del público objetivo",
  "competitors": ["competidor1.com", "competidor2.com", "competidor3.com"],
  "seasonality": "Descripción de estacionalidad (meses pico, temporadas bajas, eventos clave)",
  "seo_opportunities": [
    "Oportunidad 1",
    "Oportunidad 2",
    "Oportunidad 3"
  ],
  "initial_recommendations": [
    "Recomendación 1",
    "Recomendación 2",
    "Recomendación 3"
  ],
  "key_topics": ["tema1", "tema2", "tema3"],
  "content_strategy_notes": "Notas sobre estrategia de contenido recomendada"
}

Responde SOLO con el JSON, sin texto adicional."""


async def generate_onboarding_intelligence(url: str, extra_context: str = "") -> dict:
    """Generate an intelligence package for a new client from their website URL."""
    client = get_anthropic_client()

    user_message = f"Analiza este sitio web para un informe de onboarding de cliente: {url}"
    if extra_context:
        user_message += f"\n\nContexto adicional: {extra_context}"

    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return parse_claude_json(message)
