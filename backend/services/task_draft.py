"""Primer borrador del entregable de una tarea siguiendo su procedimiento.

La persona pide el borrador desde la tarea; Claude lo redacta con los pasos
del procedimiento y el contexto del cliente que ya hay en la app, y se guarda
como comentario marcado de IA. Nada se envía, completa ni publica solo.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.models import Task, User, WeeklyDigest
from backend.services.ai_utils import get_anthropic_client
from backend.services.inbox_processing import can_read
from backend.services.incident_report_conditions import delivery_is_confirmed

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
# Un entregable de 1.500-2.500 palabras son ~3.500 tokens de salida, más el
# razonamiento. A ~60 tokens/s eso es poco más de un minuto: 100 s sin
# reintento (un corte por tiempo sólo se repetiría) caben en los 120 s que el
# front da a la petición.
MAX_TOKENS = 8000
TIMEOUT_SECONDS = 100.0

# Límites de cada bloque del prompt: el contexto ayuda, pero no debe crecer
# sin control con dossiers o resúmenes largos.
MAX_PROCEDURE_CHARS = 8000
MAX_DESCRIPTION_CHARS = 3000
MAX_CLIENT_CONTEXT_CHARS = 4000
MAX_REPORT_CHARS = 4000
MAX_CHECKLIST_ITEMS = 40

SYSTEM_PROMPT = """Eres un consultor senior de una agencia de marketing digital y SEO (Magnify).
Preparas el PRIMER BORRADOR del entregable de una tarea recurrente siguiendo su procedimiento escrito.

Reglas:
- Sigue los pasos del procedimiento en orden. El borrador es el resultado de aplicarlos, no un resumen de ellos.
- Usa sólo los datos que recibes. Si un paso necesita datos que no tienes (cifras, exportaciones,
  accesos a herramientas), deja un hueco visible como [PENDIENTE: qué falta y de dónde sacarlo].
  Nunca inventes cifras, fechas, URLs ni resultados.
- El documento de referencia sólo se cita por su enlace: no lo has leído.
- Escribe en español, en Markdown limpio (títulos, listas, tablas si ayudan), listo para que una persona lo revise y lo pegue.
- Devuelve sólo el borrador, sin preámbulo ni comentarios sobre lo que has hecho."""


class TaskDraftError(Exception):
    """El borrador no se pudo generar. `detail` es apto para enseñar al usuario."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[…recortado]"


def _report_text(content: dict | None) -> str:
    """Texto plano de las secciones de un resumen ya entregado al cliente."""
    if not isinstance(content, dict):
        return ""
    sections = content.get("sections") or {}
    labels = {"done": "Hecho", "need": "Necesitamos", "next": "Próximos pasos"}
    lines: list[str] = []
    for key, label in labels.items():
        items = sections.get(key) or []
        if not items:
            continue
        lines.append(f"{label}:")
        for item in items:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                description = str(item.get("description") or "").strip()
                lines.append(f"- {title}: {description}" if description else f"- {title}")
            else:
                lines.append(f"- {item}")
    return "\n".join(lines)


async def collect_draft_context(db, task: Task, user: User) -> dict:
    """Datos del prompt. Cada fuente sólo entra si quien pide puede leerla.

    El borrador queda como comentario visible para quien lee la tarea, así que
    no puede llevar el dossier del cliente o sus resúmenes a quien no los ve.
    """
    client = task.client or (task.project.client if task.project else None)
    context: dict = {
        "task_title": task.title,
        "task_description": _clip(task.description, MAX_DESCRIPTION_CHARS),
        "procedure_text": _clip(task.procedure_text, MAX_PROCEDURE_CHARS),
        "procedure_url": (task.procedure_url or "").strip(),
        "checklist": [item.text for item in (task.checklist_items or [])][:MAX_CHECKLIST_ITEMS],
        "project_name": task.project.name if task.project else None,
        "client_name": client.name if client else None,
        "client_context": "",
        "last_report": None,
    }
    if client is None:
        return context
    if can_read(user, "clients"):
        context["client_context"] = _clip(client.context, MAX_CLIENT_CONTEXT_CHARS)
    if can_read(user, "digests"):
        digest = (await db.execute(
            select(WeeklyDigest)
            .where(WeeklyDigest.client_id == client.id, delivery_is_confirmed())
            .order_by(WeeklyDigest.period_end.desc(), WeeklyDigest.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        text = _clip(_report_text(digest.content) if digest else "", MAX_REPORT_CHARS)
        if digest and text:
            context["last_report"] = {
                "period_start": digest.period_start.isoformat(),
                "period_end": digest.period_end.isoformat(),
                "text": text,
            }
    return context


def build_draft_prompt(context: dict) -> str:
    parts = [f"<tarea>\nTítulo: {context['task_title']}"]
    if context.get("project_name"):
        parts.append(f"Proyecto: {context['project_name']}")
    if context.get("client_name"):
        parts.append(f"Cliente: {context['client_name']}")
    if context.get("task_description"):
        parts.append(f"Descripción:\n{context['task_description']}")
    parts.append("</tarea>")
    parts.append(f"<procedimiento>\n{context['procedure_text']}\n</procedimiento>")
    if context.get("checklist"):
        parts.append("<checklist>\n" + "\n".join(f"- {item}" for item in context["checklist"]) + "\n</checklist>")
    if context.get("procedure_url"):
        parts.append(f"<documento_de_referencia>{context['procedure_url']}</documento_de_referencia>")
    if context.get("client_context"):
        parts.append(f"<contexto_cliente>\n{context['client_context']}\n</contexto_cliente>")
    report = context.get("last_report")
    if report:
        parts.append(
            f"<ultimo_resumen_entregado periodo=\"{report['period_start']} a {report['period_end']}\">\n"
            f"{report['text']}\n</ultimo_resumen_entregado>"
        )
    parts.append("Redacta el primer borrador del entregable de esta tarea siguiendo el procedimiento.")
    return "\n".join(parts)


async def generate_task_draft(prompt: str) -> str:
    """Llama a Claude y devuelve el borrador en Markdown o lanza TaskDraftError."""
    try:
        client = get_anthropic_client().with_options(timeout=TIMEOUT_SECONDS, max_retries=0)
    except ValueError as exc:
        raise TaskDraftError("La IA no está configurada en este entorno.") from exc
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS + 5):
            message = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                # El SDK fijado (0.49) no conoce estos parámetros: van tal cual.
                # `fallbacks` reintenta en otro modelo si un filtro rechaza la petición.
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"output_config": {"effort": "medium"}, "fallbacks": "default"},
            )
    except TimeoutError as exc:
        logger.warning("Task draft timed out")
        raise TaskDraftError("La IA tardó demasiado. Inténtalo de nuevo en un momento.") from exc
    except Exception as exc:
        logger.exception("Task draft provider call failed")
        raise TaskDraftError("No se pudo generar el borrador. Inténtalo de nuevo en un momento.") from exc

    if getattr(message, "stop_reason", None) == "refusal":
        raise TaskDraftError("La IA rechazó redactar este borrador.")
    text = "\n\n".join(
        block.text for block in (message.content or [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ).strip()
    if not text:
        raise TaskDraftError("La IA no devolvió ningún borrador. Inténtalo de nuevo.")
    if getattr(message, "stop_reason", None) == "max_tokens":
        text += "\n\n[El borrador se cortó por longitud: complétalo a mano.]"
    logger.info("Task draft generated: %s chars", len(text))
    return text
