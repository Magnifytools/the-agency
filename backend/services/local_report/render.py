"""Generar el informe con la plantilla del cliente y comprobarlo antes de darlo por bueno.

La plantilla (`backend/report_templates/<plantilla>/generar.py`, Jinja2 +
Chromium vía Playwright) escribe el HTML autónomo con el PDF incrustado y el
PDF suelto. Se ejecuta en un hilo con techo de tiempo: Chromium y el render
son CPU y este proceso también sirve la API.

Comprobaciones (apartado 4 del encargo y 6 de la skill):
- clics del mes = total de Search Console;
- 11 secciones y 8 iconos en el resumen;
- el PDF incrustado es idéntico al suelto;
- ningún texto dice "simulado", "ejemplo", "ficticio/a", "de muestra" ni
  "dato real", ni lleva comillas angulares ni guion largo.
"""
from __future__ import annotations

import asyncio
import base64
import importlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "report_templates"
RENDER_TIMEOUT_SECONDS = 120
EXPECTED_SECTIONS = 11
EXPECTED_ICONS = 8

FORBIDDEN = re.compile(
    r"\bsimulad[oa]s?\b|\bejemplos?\b|\bfictici[oa]s?\b|\b(?:informe|datos?|cifras?|valores?) de muestra\b"
    r"|\bmuestra\s*:|\bdatos? real(?:es)?\b",
    re.IGNORECASE,
)
# Comillas angulares y guion largo como puntuación (CONTINUIDAD, apartado 3.9).
FORBIDDEN_CHARS = ("«", "»", "—")


class RenderError(Exception):
    pass


def templates() -> list[str]:
    return sorted(p.name for p in TEMPLATES_DIR.iterdir()
                  if p.is_dir() and (p / "generar.py").exists() and (p / "config.json").exists())


def template_dir(name: str) -> Path:
    if name not in templates():
        raise RenderError(f"No existe la plantilla \"{name}\".")
    return TEMPLATES_DIR / name


def template_defaults(name: str) -> dict:
    return json.loads((template_dir(name) / "config.json").read_text(encoding="utf-8"))


def template_roadmap(name: str) -> dict:
    return json.loads((template_dir(name) / "roadmap.json").read_text(encoding="utf-8"))


def required_text_keys(name: str) -> list[str]:
    return list(_module(name).TEXTOS_EJEMPLO)


def _module(name: str):
    template_dir(name)
    return importlib.import_module(f"backend.report_templates.{name}.generar")


@dataclass
class Rendered:
    stem: str
    html: bytes
    pdf: bytes
    checks: dict[str, Any]


def _render_sync(name: str, datos: dict, roadmap: dict) -> Rendered:
    module = _module(name)
    with tempfile.TemporaryDirectory(prefix="informe-") as tmp:
        try:
            html_path, pdf_path = module.render(json.loads(json.dumps(datos)), json.loads(json.dumps(roadmap)),
                                                Path(tmp))
        except ValueError as exc:  # validaciones de la plantilla (textos que faltan, estados…)
            raise RenderError(str(exc)) from exc
        html, pdf = html_path.read_bytes(), pdf_path.read_bytes()
        return Rendered(html_path.stem, html, pdf, {})


async def render(name: str, datos: dict, roadmap: dict) -> Rendered:
    try:
        rendered = await asyncio.wait_for(asyncio.to_thread(_render_sync, name, datos, roadmap),
                                          timeout=RENDER_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise RenderError("Generar el informe ha tardado demasiado. Prueba otra vez en un momento.") from exc
    rendered.checks = check(rendered.html, rendered.pdf, datos, roadmap)
    return rendered


# ── Comprobaciones ───────────────────────────────────────────────────


def _strings(value, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


# Lo que se escribe para el cliente (no los nombres internos del plan ni las rutas).
_PUBLIC_DATOS = ("informe", "editorial", "textos", "tecnico", "google")
_PUBLIC_TASK_KEYS = ("nombre_publico", "detalle_publico", "motivo")


def text_problems(datos: dict, roadmap: dict) -> list[dict]:
    found = []
    candidates = [item for key in _PUBLIC_DATOS for item in _strings(datos.get(key), key)]
    for mon, month in (roadmap.get("meses") or {}).items():
        candidates.append((f"roadmap.{mon}.titulo_publico", month.get("titulo_publico") or ""))
        for index, task in enumerate(month.get("tareas") or []):
            for key in _PUBLIC_TASK_KEYS:
                candidates.append((f"roadmap.{mon}.tareas[{index}].{key}", task.get(key) or ""))
    for path, value in candidates:
        match = FORBIDDEN.search(value)
        if match:
            found.append({"campo": path, "problema": f"dice \"{match.group(0)}\""})
        for char in FORBIDDEN_CHARS:
            if char in value:
                found.append({"campo": path, "problema": "comillas angulares" if char != "—"
                              else "guion largo"})
                break
    return found


def check(html: bytes, pdf: bytes, datos: dict, roadmap: dict) -> dict[str, Any]:
    page = html.decode("utf-8")
    sections = re.findall(r"<section[^>]*\bclass=\"[^\"]*\bsection\b", page)
    summary = re.search(r"<section[^>]*id=\"resumen\".*?</section>", page, flags=re.S)
    icons = summary.group(0).count("class=\"executive-icon\"") if summary else 0
    embedded = re.search(r"<script[^>]*id=\"embedded-pdf\"[^>]*>(.*?)</script>", page, flags=re.S)
    embedded_pdf = base64.b64decode(embedded.group(1).strip()) if embedded and embedded.group(1).strip() else b""
    gsc = datos.get("gsc") or {}
    expected_total = (datos.get("contexto") or {}).get("clics_total_search_console")
    items = [
        {"clave": "clics", "ok": expected_total is not None and gsc.get("clics_mes") == expected_total,
         "detalle": f"Clics del mes {gsc.get('clics_mes')} · total de Search Console {expected_total}"},
        {"clave": "secciones", "ok": len(sections) == EXPECTED_SECTIONS,
         "detalle": f"{len(sections)} secciones (se esperan {EXPECTED_SECTIONS})"},
        {"clave": "iconos", "ok": icons == EXPECTED_ICONS,
         "detalle": f"{icons} iconos en el resumen (se esperan {EXPECTED_ICONS})"},
        {"clave": "pdf", "ok": bool(embedded_pdf) and embedded_pdf == pdf,
         "detalle": "El PDF incrustado es idéntico al suelto" if embedded_pdf == pdf
         else "El PDF incrustado no coincide con el suelto"},
    ]
    problems = text_problems(datos, roadmap)
    items.append({"clave": "textos", "ok": not problems,
                  "detalle": "Sin palabras prohibidas" if not problems
                  else f"{len(problems)} textos con problemas", "problemas": problems})
    return {"ok": all(i["ok"] for i in items), "items": items}
