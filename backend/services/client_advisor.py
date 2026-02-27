"""AI Client Advisor: generates actionable recommendations based on client data."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

import anthropic
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import (
    Client, Task, TaskStatus, TimeEntry, CommunicationLog,
    ClientContact, BillingEvent,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un asesor estrategico para una agencia de marketing digital (Magnify).
Tu trabajo es analizar los datos de un cliente y dar 3-5 recomendaciones accionables.

REGLAS:
1. Escribe en espanol, tono profesional pero directo.
2. Cada recomendacion debe ser concreta y accionable (no generica).
3. Prioriza: urgentes primero, luego importantes.
4. Categorias posibles: comunicacion, facturacion, tareas, rentabilidad, estrategia.
5. Si un area esta bien, no inventes problemas. Solo reporta lo relevante.
6. NO inventes datos. Solo usa lo que esta en el contexto proporcionado.
7. Responde SOLO con el JSON, sin markdown ni explicaciones.

Responde con un JSON asi:
{
  "recommendations": [
    {
      "priority": "high|medium|low",
      "category": "comunicacion|facturacion|tareas|rentabilidad|estrategia",
      "title": "Titulo corto y accionable",
      "description": "Explicacion de 1-2 frases con el contexto",
      "action": "Accion concreta a tomar"
    }
  ]
}"""


async def get_client_advice(
    db: AsyncSession,
    client_id: int,
) -> list[dict]:
    """Gather client context and call Claude for recommendations."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY no configurada")

    # Gather context
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    if not client:
        raise ValueError("Cliente no encontrado")

    today = date.today()

    # Tasks summary
    task_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.client_id == client_id)
        .group_by(Task.status)
    )
    tasks_by_status = {row[0].value: row[1] for row in task_result.all()}

    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.client_id == client_id,
            Task.due_date < datetime.utcnow(),
            Task.status != TaskStatus.completed,
        )
    )
    tasks_overdue = overdue_result.scalar() or 0

    # Recent communications count
    comm_result = await db.execute(
        select(func.count(CommunicationLog.id)).where(
            CommunicationLog.client_id == client_id,
        )
    )
    total_comms = comm_result.scalar() or 0

    # Last communication date
    last_comm_result = await db.execute(
        select(func.max(CommunicationLog.occurred_at)).where(
            CommunicationLog.client_id == client_id,
        )
    )
    last_comm_date = last_comm_result.scalar()

    # Hours this month
    first_of_month = today.replace(day=1)
    task_ids_result = await db.execute(
        select(Task.id).where(Task.client_id == client_id)
    )
    task_ids = [r[0] for r in task_ids_result.all()]

    hours_this_month = 0.0
    if task_ids:
        hours_result = await db.execute(
            select(func.sum(TimeEntry.minutes)).where(
                TimeEntry.task_id.in_(task_ids),
                TimeEntry.minutes.isnot(None),
                TimeEntry.date >= datetime.combine(first_of_month, datetime.min.time()),
            )
        )
        hours_this_month = round((hours_result.scalar() or 0) / 60, 1)

    # Billing info
    billing_info = ""
    if client.billing_cycle:
        billing_info = f"Ciclo: {client.billing_cycle.value}"
        if client.next_invoice_date:
            days_until = (client.next_invoice_date - today).days
            billing_info += f", Proxima factura: {client.next_invoice_date} ({days_until} dias)"
        if client.last_invoiced_date:
            billing_info += f", Ultima factura: {client.last_invoiced_date}"

    # Build context
    context_parts = [
        f"CLIENTE: {client.name}",
        f"Estado: {client.status.value}",
        f"Fee mensual: {client.monthly_fee or 0} {client.currency}",
        f"Presupuesto mensual: {client.monthly_budget or 0} {client.currency}",
        f"Tareas: {tasks_by_status}",
        f"Tareas vencidas: {tasks_overdue}",
        f"Total comunicaciones: {total_comms}",
        f"Ultima comunicacion: {last_comm_date or 'nunca'}",
        f"Horas este mes: {hours_this_month}h",
    ]
    if billing_info:
        context_parts.append(f"Facturacion: {billing_info}")
    if client.notes:
        context_parts.append(f"Notas: {client.notes[:300]}")

    user_prompt = (
        "Analiza los datos de este cliente y dame 3-5 recomendaciones accionables:\n\n"
        + "\n".join(context_parts)
    )

    logger.info("Generating AI advice for client %d: %s", client_id, client.name)

    ai_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()
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
        logger.error("Failed to parse AI advice response: %s", raw_text[:200])
        raise ValueError(f"Respuesta de IA no valida: {e}") from e

    recommendations = content.get("recommendations", [])
    logger.info("Generated %d recommendations for client %d", len(recommendations), client_id)

    return recommendations
