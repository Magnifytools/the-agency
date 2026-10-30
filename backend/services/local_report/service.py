"""El informe SEO local en la base de datos: configuración, versiones, fuentes,
redacción con IA, generación y entrega.

Versiones (como los resúmenes): una abierta por cliente y periodo, que se
recalcula, edita y regenera sobre la misma fila hasta que se entrega. Entregada
queda congelada (lo que recibió el cliente); "Nueva versión" la copia con sus
fuentes para corregirla.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import undefer

from backend.db import database
from backend.db.models import (
    Client, ClientLocalReport, ClientLocalReportConfig, ClientLocalReportSource, User,
)
from backend.services import ga4_live, gsc_live
from backend.services.local_report import ai, build, gsc as gsc_block, periods as periods_mod, plan, render, sources
from backend.services.seo_control import BrandMatcher
from backend.services.temporal import business_today

logger = logging.getLogger(__name__)

# Si un borrador de IA lleva más que esto "en marcha", el proceso que lo
# hacía se reinició: se da por fallido y se puede pedir otro.
AI_STALE_AFTER = timedelta(seconds=ai.TIMEOUT_SECONDS + 120)
MAX_SOURCE_BYTES = 10 * 1024 * 1024
SOURCE_TYPES = {"text/csv", "application/vnd.ms-excel", "text/plain", "image/png", "image/jpeg", "image/webp",
                "application/pdf"}
CSV_KINDS = ("gbp_actual", "gbp_anterior", "gbp_ano_anterior", "rastreo")
_background: set[asyncio.Task] = set()


class ReportError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


# ── Configuración ────────────────────────────────────────────────────


async def get_config(db, client_id: int) -> ClientLocalReportConfig | None:
    return await db.get(ClientLocalReportConfig, client_id)


async def require_config(db, client_id: int) -> ClientLocalReportConfig:
    config = await get_config(db, client_id)
    if config is None:
        raise ReportError(409, "Este cliente aún no tiene el informe SEO local configurado.")
    return config


async def create_config(db, client: Client, *, template: str, actor: User) -> ClientLocalReportConfig:
    if await get_config(db, client.id):
        raise ReportError(409, "El informe ya está configurado para este cliente.")
    try:
        defaults = render.template_defaults(template)
        roadmap = render.template_roadmap(template)
    except render.RenderError as exc:
        raise ReportError(422, str(exc)) from exc
    landing = defaults.pop("landing_url", None) or client.website or ""
    if not landing.startswith(("http://", "https://")):
        raise ReportError(422, "Falta la página principal del informe (una URL completa).")
    config = ClientLocalReportConfig(client_id=client.id, template=template, landing_url=landing,
                                     settings=defaults, roadmap=roadmap, updated_by=actor.id)
    db.add(config)
    await db.flush()
    return config


def clean_settings(value: dict) -> dict:
    """Valida lo que se puede editar desde la web (familias y nombres)."""
    if not isinstance(value, dict):
        raise ReportError(422, "La configuración tiene que ser un objeto.")
    grupos = value.get("grupos") or {}
    for key in ("tabla", "tarjeta"):
        expression = grupos.get(key)
        if expression is not None and (not isinstance(expression, str) or len(expression) > 500
                                       or not gsc_block.normalize_regex(expression)):
            raise ReportError(422, f"La familia de consultas \"{key}\" tiene que ser texto con alternativas "
                                   "separadas por |.")
    names = value.get("nombres_paginas") or {}
    if not isinstance(names, dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 120
                                          for k, v in names.items()):
        raise ReportError(422, "Los nombres de página son pares ruta → nombre (máximo 120 caracteres).")
    return value


# ── Lecturas ─────────────────────────────────────────────────────────


async def list_reports(db, client_id: int) -> list[ClientLocalReport]:
    return list((await db.scalars(
        select(ClientLocalReport).where(ClientLocalReport.client_id == client_id)
        .order_by(ClientLocalReport.period_start.desc(), ClientLocalReport.id.desc())
    )).all())


async def get_report(db, client_id: int, report_id: int, *, lock: bool = False,
                     files: bool = False) -> ClientLocalReport:
    query = select(ClientLocalReport).where(ClientLocalReport.id == report_id,
                                            ClientLocalReport.client_id == client_id)
    if files:
        query = query.options(undefer(ClientLocalReport.html), undefer(ClientLocalReport.pdf))
    if lock:
        query = query.with_for_update()
    report = (await db.execute(query)).scalar_one_or_none()
    if report is None:
        raise ReportError(404, "Informe no encontrado")
    return report


async def list_sources(db, report_id: int, *, content: bool = False) -> list[ClientLocalReportSource]:
    query = select(ClientLocalReportSource).where(ClientLocalReportSource.report_id == report_id)
    if content:
        query = query.options(undefer(ClientLocalReportSource.content))
    return list((await db.scalars(query.order_by(ClientLocalReportSource.id))).all())


def ai_state(report: ClientLocalReport) -> str | None:
    if report.ai_status == "running" and report.ai_started_at and _now() - report.ai_started_at > AI_STALE_AFTER:
        return "failed"
    return report.ai_status


def _editable(report: ClientLocalReport) -> None:
    if report.delivered_at is not None:
        raise ReportError(409, "Esta versión ya se entregó al cliente. Crea una versión nueva para cambiarla.")
    if ai_state(report) == "running":
        raise ReportError(409, "La IA está redactando los textos de esta versión. Espera a que termine.")


async def _previous(db, client_id: int, before: date) -> ClientLocalReport | None:
    """La última versión de un periodo anterior (la entregada si la hay)."""
    rows = (await db.scalars(
        select(ClientLocalReport).where(ClientLocalReport.client_id == client_id,
                                        ClientLocalReport.period_start < before)
        .order_by(ClientLocalReport.period_start.desc(), ClientLocalReport.delivered_at.desc().nulls_last(),
                  ClientLocalReport.id.desc())
    )).all()
    return rows[0] if rows else None


# ── Calcular ─────────────────────────────────────────────────────────


def _parsed_sources(rows: list[ClientLocalReportSource], business: str | None) -> dict[str, dict]:
    parsed = {}
    for row in rows:
        if row.kind in ("gbp_actual", "gbp_anterior", "gbp_ano_anterior"):
            parsed[row.kind] = sources.parse_gbp(row.content, row.filename, business=business)
        elif row.kind == "rastreo":
            parsed[row.kind] = sources.parse_crawl(row.content)
    return parsed


async def _compute(db, client: Client, config: ClientLocalReportConfig, report: ClientLocalReport | None, *,
                   start: date, end: date, today: date, inputs: dict, source_rows: list) -> tuple[dict, dict, list]:
    per = periods_mod.compute(start, end)
    previous = await _previous(db, client.id, start)
    tasks = await plan.load_tasks(db, client.id, config.project_id)
    settings = config.settings or {}
    parsed = _parsed_sources(source_rows, (settings.get("cliente") or {}).get("negocio"))

    async def gsc_run(**kwargs):
        return await gsc_live.query(db, client, **kwargs)

    ga4_run = None
    if client.ga4_property_id:
        async def ga4_query(**kwargs):
            return await ga4_live.query(db, client, **kwargs)
        ga4_run = build.ga4_runner(ga4_query)

    try:
        return await build.build(
            settings=settings, landing_url=config.landing_url, roadmap_base=config.roadmap,
            brand_terms=list(client.brand_terms or []), periods=per, today=today,
            history_start=gsc_block.history_start(today, gsc_live.HISTORY_DAYS), gsc_run=gsc_run, ga4_run=ga4_run,
            tasks=tasks, parsed_sources=parsed, inputs=inputs,
            current=report.datos if report else None, current_roadmap=report.roadmap if report else None,
            previous=previous.datos if previous else None, previous_roadmap=previous.roadmap if previous else None,
        )
    except gsc_live.GscLiveError as exc:
        raise ReportError(exc.status if exc.status < 500 else 502, exc.message) from exc


def _check_period(start: date, end: date, today: date) -> None:
    if start > end:
        raise ReportError(422, "El inicio del periodo no puede ser posterior al final.")
    if end >= today:
        raise ReportError(422, "El periodo tiene que acabar antes de hoy.")
    if start < today - timedelta(days=gsc_live.HISTORY_DAYS) + timedelta(days=31):
        raise ReportError(422, "Search Console sólo guarda 16 meses: para un mes tan antiguo no hay con qué "
                               "comparar. Si ya se hizo, usa la versión guardada.")


async def create_report(db, client: Client, *, start: date, end: date, actor: User,
                        today: date | None = None) -> ClientLocalReport:
    today = today or business_today()
    _check_period(start, end, today)
    config = await require_config(db, client.id)
    existing = (await db.scalars(select(ClientLocalReport).where(
        ClientLocalReport.client_id == client.id, ClientLocalReport.period_start == start,
        ClientLocalReport.period_end == end, ClientLocalReport.delivered_at.is_(None)))).first()
    if existing:
        raise ReportError(409, f"Ya hay una versión abierta de ese periodo (#{existing.id}).")
    datos, roadmap, warnings = await _compute(db, client, config, None, start=start, end=end, today=today,
                                              inputs={}, source_rows=[])
    report = ClientLocalReport(client_id=client.id, period_start=start, period_end=end, datos=datos,
                               roadmap=roadmap, inputs={}, warnings=warnings, computed_at=_now(),
                               created_by=actor.id)
    db.add(report)
    await db.flush()
    return report


async def recompute(db, client: Client, report: ClientLocalReport, *, today: date | None = None) -> None:
    """Vuelve a pedir las cifras (Search Console, Analytics, tareas) y conserva los textos."""
    _editable(report)
    config = await require_config(db, client.id)
    rows = await list_sources(db, report.id, content=True)
    try:
        datos, roadmap, warnings = await _compute(
            db, client, config, report, start=report.period_start, end=report.period_end,
            today=today or business_today(), inputs=report.inputs or {}, source_rows=rows)
    except sources.SourceError as exc:
        raise ReportError(422, str(exc)) from exc
    report.datos, report.roadmap, report.warnings = datos, roadmap, warnings
    report.computed_at = _now()
    _invalidate(report)


def _invalidate(report: ClientLocalReport) -> None:
    """Los archivos generados ya no corresponden a los datos: hay que volver a generar."""
    report.html = None
    report.pdf = None
    report.generated_at = None
    report.generated_by = None
    report.checks = None


async def refresh_manual(db, client: Client, report: ClientLocalReport) -> None:
    """Rehace la ficha y el rastreo con lo subido, sin volver a preguntar a Google."""
    config = await require_config(db, client.id)
    per = periods_mod.compute(report.period_start, report.period_end)
    rows = await list_sources(db, report.id, content=True)
    settings = config.settings or {}
    try:
        parsed = _parsed_sources(rows, (settings.get("cliente") or {}).get("negocio"))
    except sources.SourceError as exc:
        raise ReportError(422, str(exc)) from exc
    inputs = report.inputs or {}
    datos = copy.deepcopy(report.datos)
    google, google_warnings = build.google_block(parsed, inputs, per,
                                                 brand=BrandMatcher(list(client.brand_terms or [])),
                                                 settings=settings)
    datos["google"] = google
    datos["tecnico"] = build.tecnico_block(datos.get("tecnico") or {}, parsed.get("rastreo"), inputs, per)
    datos.setdefault("contexto", {})["observaciones"] = inputs.get("observaciones") or ""
    # Los avisos de la ficha se rehacen; los demás (Search Console, plan) se quedan.
    kept = [w for w in report.warnings or [] if not w.startswith(("Ficha de Google", "Falta el CSV de la ficha",
                                                                    "Falta la cifra de búsquedas", "La captura dice"))]
    report.datos, report.warnings = datos, kept + google_warnings
    _invalidate(report)


# ── Fuentes y datos a mano ───────────────────────────────────────────


async def add_source(db, client: Client, report: ClientLocalReport, *, kind: str, filename: str,
                     content_type: str, content: bytes, actor: User) -> ClientLocalReportSource:
    _editable(report)
    if kind not in ("gbp_actual", "gbp_anterior", "gbp_ano_anterior", "rastreo", "captura", "otro"):
        raise ReportError(422, "Tipo de archivo desconocido.")
    if not content:
        raise ReportError(422, "El archivo está vacío.")
    if len(content) > MAX_SOURCE_BYTES:
        raise ReportError(413, "El archivo pesa más de 10 MB.")
    content_type = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if kind in CSV_KINDS:
        if not filename.lower().endswith(".csv"):
            raise ReportError(415, "Sube la exportación en CSV.")
        content_type = "text/csv"
        try:
            sources.parse_gbp(content, filename) if kind.startswith("gbp") else sources.parse_crawl(content)
        except sources.SourceError as exc:
            raise ReportError(422, str(exc)) from exc
        # Uno por tipo: el nuevo sustituye al anterior.
        for old in await list_sources(db, report.id):
            if old.kind == kind:
                await db.delete(old)
    elif content_type not in SOURCE_TYPES:
        raise ReportError(415, "Sube una imagen (PNG, JPG, WebP), un PDF o un CSV.")
    row = ClientLocalReportSource(report_id=report.id, kind=kind, filename=filename[:255],
                                  content_type=content_type, content=content, size=len(content),
                                  uploaded_by=actor.id)
    db.add(row)
    await db.flush()
    if kind in CSV_KINDS:
        await refresh_manual(db, client, report)
    return row


async def remove_source(db, client: Client, report: ClientLocalReport, source_id: int) -> None:
    _editable(report)
    row = await db.get(ClientLocalReportSource, source_id)
    if row is None or row.report_id != report.id:
        raise ReportError(404, "Archivo no encontrado")
    kind = row.kind
    await db.delete(row)
    await db.flush()
    if kind in CSV_KINDS:
        await refresh_manual(db, client, report)


def clean_inputs(value: dict) -> dict:
    out: dict[str, Any] = {}
    searches = value.get("busquedas")
    if searches in (None, "", "Pendiente") or (isinstance(searches, int) and searches >= 0):
        out["busquedas"] = searches if searches != "" else None
    else:
        raise ReportError(422, "Búsquedas: un número o \"Pendiente\".")
    people = value.get("personas_panel")
    if people is not None and not (isinstance(people, int) and people >= 0):
        raise ReportError(422, "Personas que vieron la ficha (captura): un número.")
    out["personas_panel"] = people
    terms = []
    for item in value.get("terminos") or []:
        q = " ".join(str(item.get("q") or "").split())[:200]
        count = item.get("apariciones")
        if not q:
            continue
        if not (isinstance(count, int) and count >= 0):
            raise ReportError(422, f"El término \"{q}\" necesita su número de apariciones.")
        tipo = item.get("tipo")
        terms.append({"q": q, "apariciones": count, **({"tipo": str(tipo)[:40]} if tipo else {})})
    out["terminos"] = terms[:50]
    out["observaciones"] = str(value.get("observaciones") or "")[:4000]
    crawl_day = value.get("fecha_rastreo")
    if crawl_day:
        try:
            out["fecha_rastreo"] = date.fromisoformat(str(crawl_day)).isoformat()
        except ValueError as exc:
            raise ReportError(422, "Fecha del rastreo no válida.") from exc
    return out


async def update_inputs(db, client: Client, report: ClientLocalReport, value: dict) -> None:
    _editable(report)
    report.inputs = clean_inputs(value)
    await refresh_manual(db, client, report)


# ── Textos ───────────────────────────────────────────────────────────


def _text(value, limit: int = 6000) -> str:
    if not isinstance(value, str):
        raise ReportError(422, "Los textos tienen que ser texto.")
    return value.replace("«", "\"").replace("»", "\"").strip()[:limit]


def _rows(value) -> list[dict]:
    if not isinstance(value, list):
        raise ReportError(422, "Las filas técnicas son una lista.")
    return [{k: _text(item.get(k) or "", 600) for k in ("titulo", "detalle", "estado", "siguiente")}
            for item in value if isinstance(item, dict) and (item.get("titulo") or "").strip()]


async def update_texts(db, report: ClientLocalReport, body: dict, *, template: str) -> None:
    """Edición de la web: textos, lectura de cada sección, filas técnicas,
    nombres de página, intención de las consultas de grupos y motivos de espera."""
    _editable(report)
    datos = copy.deepcopy(report.datos)
    roadmap = copy.deepcopy(report.roadmap)
    keys = set(render.required_text_keys(template))
    for key, value in (body.get("textos") or {}).items():
        if key not in keys:
            raise ReportError(422, f"Texto desconocido: {key}")
        datos["textos"][key] = _text(value, 1500)
    for key, value in (body.get("editorial") or {}).items():
        if key not in build.EDITORIAL_KEYS:
            raise ReportError(422, f"Sección desconocida: {key}")
        datos["editorial"][key] = _text(value)
    for key in ("modo", "nota"):
        if key in (body.get("informe") or {}):
            datos["informe"][key] = _text(body["informe"][key], 1500)
    tecnico = body.get("tecnico") or {}
    for key in ("filas_rastreo", "otros"):
        if key in tecnico:
            datos["tecnico"][key] = _rows(tecnico[key])
    names = body.get("nombres_paginas") or {}
    for page in datos["gsc"].get("paginas") or []:
        if page["ruta"] in names:
            page["nombre"] = _text(names[page["ruta"]], 120) or page["nombre"]
    intents = body.get("intenciones_grupos") or {}
    for row in (datos.get("grupos") or {}).get("consultas") or []:
        if row["q"] in intents:
            row["intencion"] = _text(intents[row["q"]], 60) or row["intencion"]
    motivos = {int(k): v for k, v in (body.get("motivos") or {}).items() if str(k).isdigit()}
    for month in (roadmap.get("meses") or {}).values():
        for task in month.get("tareas") or []:
            if task.get("estado") == "bloqueado" and task.get("tarea_id") in motivos:
                task["motivo"] = _text(motivos[task["tarea_id"]], 300)
    report.datos, report.roadmap = datos, roadmap
    _invalidate(report)


# ── IA ───────────────────────────────────────────────────────────────


async def start_draft(db, report: ClientLocalReport, *, template: str, tone: dict | None) -> None:
    _editable(report)
    prompt = ai.build_prompt(template, report.datos, report.roadmap,
                             text_keys=render.required_text_keys(template), tone=tone)
    report.ai_status = "running"
    report.ai_started_at = _now()
    report.ai_error = None
    await db.commit()
    task = asyncio.create_task(_run_draft(report.id, prompt, template, report.ai_started_at))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _run_draft(report_id: int, prompt: str, template: str, started_at: datetime,
                     *, draft_fn=None, session_factory=None) -> None:
    draft_fn = draft_fn or ai.draft
    session_factory = session_factory or database.async_session
    try:
        result, error = await draft_fn(prompt), None
    except ai.DraftError as exc:
        result, error = None, str(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Local report draft failed")
        result, error = None, "No se pudo redactar el borrador."
    async with session_factory() as db:
        report = (await db.execute(select(ClientLocalReport).where(ClientLocalReport.id == report_id)
                                   .with_for_update())).scalar_one_or_none()
        # Si entretanto se pidió otro borrador o se entregó, éste no pisa nada.
        if report is None or report.ai_started_at != started_at or report.delivered_at is not None:
            return
        if error:
            report.ai_status, report.ai_error = "failed", error
        else:
            datos, roadmap, missing = ai.apply_draft(
                report.datos, report.roadmap, result, text_keys=render.required_text_keys(template),
                editorial_keys=list(build.EDITORIAL_KEYS))
            report.datos, report.roadmap = datos, roadmap
            report.ai_status, report.ai_drafted_at = "done", _now()
            report.ai_error = ("La IA dejó sin redactar: " + ", ".join(missing)) if missing else None
            _invalidate(report)
        await db.commit()


async def tone_for(db, report: ClientLocalReport) -> dict | None:
    """Los textos del último informe entregado (o generado) de otro periodo."""
    rows = (await db.scalars(
        select(ClientLocalReport).where(ClientLocalReport.client_id == report.client_id,
                                        ClientLocalReport.id != report.id,
                                        ClientLocalReport.generated_at.isnot(None))
        .order_by(ClientLocalReport.delivered_at.desc().nulls_last(), ClientLocalReport.period_start.desc())
    )).all()
    for row in rows:
        if (row.period_start, row.period_end) != (report.period_start, report.period_end):
            datos = row.datos or {}
            return {"periodo": f"{row.period_start.isoformat()} a {row.period_end.isoformat()}",
                    "informe": {k: (datos.get("informe") or {}).get(k) for k in ("modo", "nota")},
                    "editorial": datos.get("editorial"), "textos": datos.get("textos"),
                    "tecnico": {k: (datos.get("tecnico") or {}).get(k) for k in ("filas_rastreo", "otros")}}
    return None


# ── Generar y entregar ───────────────────────────────────────────────


async def generate(db, report: ClientLocalReport, *, template: str, actor: User) -> None:
    _editable(report)
    missing = [k for k in render.required_text_keys(template) if not (report.datos.get("textos") or {}).get(k)]
    if missing:
        raise ReportError(422, f"Faltan {len(missing)} textos por escribir (o redactar con IA): "
                               + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""))
    await db.commit()  # Chromium tarda: sin transacción abierta mientras tanto.
    try:
        rendered = await render.render(template, report.datos, report.roadmap)
    except render.RenderError as exc:
        raise ReportError(422, str(exc)) from exc
    report.html, report.pdf, report.file_stem = rendered.html, rendered.pdf, rendered.stem
    report.checks = rendered.checks
    report.generated_at = _now()
    report.generated_by = actor.id


async def deliver(db, report: ClientLocalReport, *, actor: User) -> None:
    if report.delivered_at is not None:
        raise ReportError(409, "Esta versión ya consta como entregada.")
    if report.generated_at is None:
        raise ReportError(409, "Genera el informe antes de marcarlo como entregado.")
    if not (report.checks or {}).get("ok"):
        raise ReportError(409, "Las comprobaciones del informe no han pasado: revísalas antes de entregarlo.")
    report.delivered_at = _now()
    report.delivered_by = actor.id


async def new_version(db, report: ClientLocalReport, *, actor: User) -> ClientLocalReport:
    if report.delivered_at is None:
        raise ReportError(409, "Esta versión aún no se ha entregado: se puede cambiar directamente.")
    open_one = (await db.scalars(select(ClientLocalReport).where(
        ClientLocalReport.client_id == report.client_id, ClientLocalReport.period_start == report.period_start,
        ClientLocalReport.period_end == report.period_end, ClientLocalReport.delivered_at.is_(None)))).first()
    if open_one:
        raise ReportError(409, f"Ya hay una versión abierta de ese periodo (#{open_one.id}).")
    copy_row = ClientLocalReport(
        client_id=report.client_id, period_start=report.period_start, period_end=report.period_end,
        datos=copy.deepcopy(report.datos), roadmap=copy.deepcopy(report.roadmap),
        inputs=copy.deepcopy(report.inputs or {}), warnings=list(report.warnings or []),
        computed_at=report.computed_at, ai_drafted_at=report.ai_drafted_at, created_by=actor.id)
    db.add(copy_row)
    await db.flush()
    for src in await list_sources(db, report.id, content=True):
        db.add(ClientLocalReportSource(report_id=copy_row.id, kind=src.kind, filename=src.filename,
                                       content_type=src.content_type, content=src.content, size=src.size,
                                       uploaded_by=src.uploaded_by))
    await db.flush()
    return copy_row
