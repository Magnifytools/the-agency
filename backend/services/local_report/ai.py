"""Borrador con IA de los textos del informe: lectura de cada sección, las 29 notas
de periodo y fuente, el modo y la nota del informe, las filas técnicas y el
motivo para el cliente de cada tarea en espera.

Recibe las cifras YA calculadas (agregados de Search Console y GA4 en vivo, la
ficha y el rastreo que subió el equipo), nunca las tablas guardadas de Search
Console: la guardia de privacidad lo vigila. Es un borrador: se guarda en la
versión y el equipo lo revisa y edita antes de generar.

Las reglas están junto a la plantilla (`redaccion.md`, `textos_guia.json`) y el
tono sale del último informe del cliente o, si no hay, de la referencia de
octubre de 2026 (`tono_referencia.json`).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from types import SimpleNamespace
from typing import Any

from backend.services.ai_utils import get_anthropic_client, parse_claude_json
from backend.services.local_report.render import template_dir

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
# ~40 textos de una a cinco frases: unos 8.000 tokens de salida. Con effort
# medium tarda del orden de 1-3 minutos; corre en segundo plano.
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 420


class DraftError(Exception):
    pass


SYSTEM_PROMPT = """Eres consultor sénior de SEO local y redactas el informe mensual que recibe un restaurante.
Escribes en español de España, claro y cercano, para alguien que no sabe de SEO.
Usa SOLO las cifras que te dan: no inventes datos, periodos ni causas.
Responde únicamente con un objeto JSON válido, sin texto antes ni después."""


def _without(datos: dict, *keys: str) -> dict:
    out = copy.deepcopy(datos)
    for key in keys:
        out.pop(key, None)
    return out


def _public_plan(roadmap: dict) -> dict:
    meses = {}
    for mon, month in sorted((roadmap.get("meses") or {}).items()):
        meses[mon] = {
            "titulo": month.get("titulo_publico") or month.get("titulo"),
            "tareas": [{"tarea_id": t.get("tarea_id"), "nombre": t.get("nombre_publico") or t.get("nombre"),
                        "estado": t.get("estado"), "evidencia": t.get("evidencia"), "motivo": t.get("motivo")}
                       for t in month.get("tareas") or []],
        }
    return meses


def build_prompt(template: str, datos: dict, roadmap: dict, *, text_keys: list[str],
                 tone: dict | None) -> str:
    base = template_dir(template)
    rules = (base / "redaccion.md").read_text(encoding="utf-8")
    guide = json.loads((base / "textos_guia.json").read_text(encoding="utf-8"))
    if tone is None:
        tone = json.loads((base / "tono_referencia.json").read_text(encoding="utf-8"))
    context = datos.get("contexto") or {}
    data = _without(datos, "editorial", "textos", "contexto")
    new_crawl = bool((datos.get("tecnico") or {}).get("rastreo_nuevo"))
    waiting = context.get("tareas_en_espera") or []
    parts = [
        f"<reglas>\n{rules}\n</reglas>",
        "<que_va_en_cada_texto>\n" + json.dumps(guide, ensure_ascii=False, indent=1) + "\n</que_va_en_cada_texto>",
        "<informe_anterior_para_el_tono>\n" + json.dumps(tone, ensure_ascii=False, indent=1)
        + "\n</informe_anterior_para_el_tono>\n"
        "Imita el tono, la longitud y el nivel de detalle, pero con las cifras y periodos de ESTE informe: "
        "no copies frases que ya no sean ciertas.",
        "<datos_del_informe>\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n</datos_del_informe>",
        "<contexto_para_redactar>\n" + json.dumps(context, ensure_ascii=False, indent=1) + "\n</contexto_para_redactar>",
        "<plan_de_trabajo>\n" + json.dumps(_public_plan(roadmap), ensure_ascii=False, indent=1) + "\n</plan_de_trabajo>",
    ]
    if context.get("observaciones"):
        parts.append("Las observaciones del equipo van en contexto_para_redactar.observaciones: inclúyelas donde "
                     "encajen, con sus palabras.")
    parts.append(
        "Devuelve este JSON:\n"
        "{\n"
        '  "informe": {"modo": "...", "nota": "..."},\n'
        '  "editorial": {' + ", ".join(f'"{k}": "..."' for k in guide["editorial"]) + "},\n"
        '  "textos": {' + ", ".join(f'"{k}": "..."' for k in text_keys) + "},\n"
        '  "tecnico": {"otros": [{"titulo", "detalle", "estado", "siguiente"}]'
        + (', "filas_rastreo": [{"titulo", "detalle", "estado", "siguiente"}]' if new_crawl else "") + "},\n"
        '  "motivos": [{"tarea_id": 0, "motivo": "..."}]\n'
        "}\n"
        "- informe.modo: una línea con el periodo de los datos; informe.nota: dos o tres frases sobre qué es "
        "parcial o qué falta, o sobre las fuentes.\n"
        "- editorial.analytics: cadena vacía si ga4.disponible es false.\n"
        "- tecnico.otros: el estado y el siguiente paso de cada incidencia técnica no ligada al rastreo, "
        "coherentes con el plan de trabajo (mismo título y orden que en datos_del_informe.tecnico.otros).\n"
        + ("- tecnico.filas_rastreo: la situación real de los enlaces que redirigen según tecnico.rastreo_nuevo, "
           "comparada con el estudio inicial (tecnico.estudio_inicial).\n" if new_crawl else "")
        + ("- motivos: para cada tarea de contexto_para_redactar.tareas_en_espera, por qué está en espera, en "
           "lenguaje de cliente, a partir de \"esperando\" (p. ej. \"Pendiente de que el restaurante confirme "
           "horarios y categoría\").\n" if waiting else "- motivos: lista vacía.\n")
        + f"- Los {len(text_keys)} textos son obligatorios y no pueden ir vacíos (salvo editorial.analytics)."
    )
    return "\n\n".join(parts)


async def draft(prompt: str) -> dict[str, Any]:
    try:
        client = get_anthropic_client().with_options(timeout=TIMEOUT_SECONDS, max_retries=0)
    except ValueError as exc:
        raise DraftError("La IA no está configurada en este entorno.") from exc
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS + 5):
            message = await client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                # El SDK fijado (0.49) no conoce estos parámetros: van tal cual (como en task_draft).
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"output_config": {"effort": "medium"}, "fallbacks": "default"},
            )
    except TimeoutError as exc:
        raise DraftError("La IA tardó demasiado. Inténtalo de nuevo en un momento.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Local report draft provider call failed")
        raise DraftError("No se pudo redactar el borrador. Inténtalo de nuevo en un momento.") from exc
    stop = getattr(message, "stop_reason", None)
    if stop == "max_tokens":
        raise DraftError("La respuesta de la IA se cortó por longitud. Inténtalo de nuevo.")
    if stop == "refusal":
        raise DraftError("La IA rechazó redactar este borrador.")
    # Puede llegar un bloque de razonamiento antes del texto: se juntan sólo los de texto.
    text = "\n".join(block.text for block in (message.content or [])
                     if getattr(block, "type", None) == "text" and getattr(block, "text", None))
    try:
        return parse_claude_json(SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)]))
    except ValueError as exc:
        logger.warning("Local report draft: respuesta sin JSON válido (stop=%s, bloques=%s, %s caracteres)",
                       stop, [getattr(b, "type", None) for b in message.content or []], len(text))
        raise DraftError("La IA no devolvió un borrador válido. Inténtalo de nuevo.") from exc


def _clean(value) -> str:
    text = value if isinstance(value, str) else ""
    return text.replace("«", "\"").replace("»", "\"").strip()


def _rows(value) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    rows = [{k: _clean(item.get(k)) for k in ("titulo", "detalle", "estado", "siguiente")}
            for item in value if isinstance(item, dict) and _clean(item.get("titulo"))]
    return rows or None


def apply_draft(datos: dict, roadmap: dict, result: dict, *, text_keys: list[str],
                editorial_keys: list[str]) -> tuple[dict, dict, list[str]]:
    """Mezcla el borrador en la versión. Lo que falte se queda como estaba y se avisa."""
    datos, roadmap = copy.deepcopy(datos), copy.deepcopy(roadmap)
    missing: list[str] = []
    informe = result.get("informe") or {}
    for key in ("modo", "nota"):
        if _clean(informe.get(key)):
            datos["informe"][key] = _clean(informe.get(key))
    editorial = result.get("editorial") or {}
    for key in editorial_keys:
        text = _clean(editorial.get(key))
        if text or key == "analytics":
            datos["editorial"][key] = text if (key != "analytics" or (datos.get("ga4") or {}).get("disponible")) else ""
        else:
            missing.append(f"editorial.{key}")
    textos = result.get("textos") or {}
    for key in text_keys:
        text = _clean(textos.get(key))
        if text:
            datos["textos"][key] = text
        else:
            missing.append(f"textos.{key}")
    tecnico = result.get("tecnico") or {}
    for key in ("otros", "filas_rastreo"):
        rows = _rows(tecnico.get(key))
        if rows and (key == "otros" or (datos.get("tecnico") or {}).get("rastreo_nuevo")):
            datos["tecnico"][key] = rows
    motivos = {m.get("tarea_id"): _clean(m.get("motivo")) for m in result.get("motivos") or []
               if isinstance(m, dict)}
    for month in (roadmap.get("meses") or {}).values():
        for task in month.get("tareas") or []:
            if task.get("estado") == "bloqueado" and motivos.get(task.get("tarea_id")):
                task["motivo"] = motivos[task["tarea_id"]]
    return datos, roadmap, missing
