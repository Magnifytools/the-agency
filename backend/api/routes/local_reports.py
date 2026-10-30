"""Informe mensual SEO local de un cliente (pestaña "Informe SEO local").

Leer: lectura de ``digests`` (es un entregable al cliente, como los
resúmenes). Configurar, calcular, subir fuentes, editar, redactar con IA,
generar y entregar: escritura de ``digests``. Las cifras de Google se piden en
vivo con las cuentas conectadas (`gsc_live`, `ga4_live`).

Los archivos generados se devuelven siempre como descarga (el HTML lleva
scripts: nunca se ejecuta en nuestro origen).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.core.rate_limiter import ai_limiter, gsc_live_limiter
from backend.db.database import get_db
from backend.db.models import ClientLocalReport, ClientLocalReportConfig, Project, User
from backend.services.file_uploads import stored_file_response_args
from backend.services.local_report import periods, render
from backend.services.local_report import service
from backend.services.temporal import business_today

router = APIRouter(prefix="/api/clients/{client_id}/local-report", tags=["local-report"])

# Calcular son ~20 consultas a Search Console y 6 a Analytics.
COMPUTE_LIMIT_PER_MINUTE = 6


def _http(exc: service.ReportError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _summary(report: ClientLocalReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "period_label": periods.range_label(report.period_start, report.period_end),
        "file_stem": report.file_stem,
        "computed_at": _iso(report.computed_at),
        "generated_at": _iso(report.generated_at),
        "delivered_at": _iso(report.delivered_at),
        "checks_ok": (report.checks or {}).get("ok") if report.checks else None,
        "ai_status": service.ai_state(report),
        "created_at": _iso(report.created_at),
    }


def _config(config: ClientLocalReportConfig | None) -> Optional[dict]:
    if config is None:
        return None
    return {"template": config.template, "landing_url": config.landing_url, "project_id": config.project_id,
            "settings": config.settings, "roadmap": config.roadmap, "updated_at": _iso(config.updated_at)}


async def _detail(db, report: ClientLocalReport, template: str) -> dict[str, Any]:
    rows = await service.list_sources(db, report.id)
    guide = json.loads((render.template_dir(template) / "textos_guia.json").read_text(encoding="utf-8"))
    return {
        **_summary(report),
        "datos": report.datos,
        "roadmap": report.roadmap,
        "inputs": report.inputs or {},
        "warnings": report.warnings or [],
        "checks": report.checks,
        "ai_error": report.ai_error,
        "ai_drafted_at": _iso(report.ai_drafted_at),
        "sources": [{"id": s.id, "kind": s.kind, "filename": s.filename, "size": s.size,
                     "content_type": s.content_type, "created_at": _iso(s.created_at)} for s in rows],
        "text_keys": render.required_text_keys(template),
        "guide": guide,
    }


async def _client(db, client_id: int):
    return await get_client_or_404(client_id, db)


@router.get("")
async def overview(client_id: int, db: AsyncSession = Depends(get_db),
                   _: User = Depends(require_module("digests"))):
    """Configuración del cliente, plantillas disponibles y versiones."""
    await _client(db, client_id)
    config = await service.get_config(db, client_id)
    reports = await service.list_reports(db, client_id)
    start, end = periods.default_period(business_today())
    return {"config": _config(config), "templates": render.templates(),
            "default_period": {"start": start.isoformat(), "end": end.isoformat()},
            "reports": [_summary(r) for r in reports]}


class ConfigCreate(BaseModel):
    template: str = Field(min_length=1, max_length=40)


@router.post("/config", status_code=201)
async def create_config(client_id: int, body: ConfigCreate, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_module("digests", write=True))):
    client = await _client(db, client_id)
    try:
        config = await service.create_config(db, client, template=body.template, actor=user)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return _config(config)


class ConfigUpdate(BaseModel):
    landing_url: Optional[str] = Field(None, max_length=500)
    project_id: Optional[int] = None
    settings: Optional[dict] = None
    roadmap: Optional[dict] = None


@router.put("/config")
async def update_config(client_id: int, body: ConfigUpdate, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_module("digests", write=True))):
    await _client(db, client_id)
    try:
        config = await service.require_config(db, client_id)
        fields = body.model_fields_set
        if "landing_url" in fields:
            if not (body.landing_url or "").startswith(("http://", "https://")):
                raise service.ReportError(422, "La página principal tiene que ser una URL completa.")
            config.landing_url = body.landing_url.strip()
        if "project_id" in fields:
            if body.project_id is not None:
                project = await db.get(Project, body.project_id)
                if project is None or project.client_id != client_id:
                    raise service.ReportError(422, "El proyecto no es de este cliente.")
            config.project_id = body.project_id
        if "settings" in fields and body.settings is not None:
            config.settings = service.clean_settings(body.settings)
        if "roadmap" in fields and body.roadmap is not None:
            if not isinstance(body.roadmap.get("meses"), dict):
                raise service.ReportError(422, "El plan necesita la lista de meses.")
            config.roadmap = body.roadmap
    except service.ReportError as exc:
        raise _http(exc) from exc
    config.updated_by = user.id
    await db.commit()
    return _config(config)


class ReportCreate(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None


@router.post("/reports", status_code=201)
async def create_report(client_id: int, body: ReportCreate, db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_module("digests", write=True))):
    """Nueva versión de un periodo (por defecto, el mes natural anterior) con las cifras calculadas."""
    client = await _client(db, client_id)
    gsc_live_limiter.check(user.id, COMPUTE_LIMIT_PER_MINUTE, 60)
    start, end = body.period_start, body.period_end
    if (start is None) != (end is None):
        raise HTTPException(status_code=422, detail="Indica el inicio y el final del periodo, o ninguno.")
    if start is None:
        start, end = periods.default_period(business_today())
    try:
        report = await service.create_report(db, client, start=start, end=end, actor=user)
        config = await service.require_config(db, client_id)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


async def _load(db, client_id: int, report_id: int, *, lock: bool = False, files: bool = False):
    try:
        report = await service.get_report(db, client_id, report_id, lock=lock, files=files)
        config = await service.require_config(db, client_id)
    except service.ReportError as exc:
        raise _http(exc) from exc
    return report, config


@router.get("/reports/{report_id}")
async def get_report(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                     _: User = Depends(require_module("digests"))):
    report, config = await _load(db, client_id, report_id)
    return await _detail(db, report, config.template)


@router.post("/reports/{report_id}/recompute")
async def recompute(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require_module("digests", write=True))):
    client = await _client(db, client_id)
    gsc_live_limiter.check(user.id, COMPUTE_LIMIT_PER_MINUTE, 60)
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.recompute(db, client, report)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.put("/reports/{report_id}/inputs")
async def update_inputs(client_id: int, report_id: int, body: dict, db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_module("digests", write=True))):
    """Lo que no tiene The Agency: búsquedas y términos de la ficha, observaciones, fecha del rastreo."""
    client = await _client(db, client_id)
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.update_inputs(db, client, report, body)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.patch("/reports/{report_id}/texts")
async def update_texts(client_id: int, report_id: int, body: dict, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_module("digests", write=True))):
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.update_texts(db, report, body, template=config.template)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.post("/reports/{report_id}/sources", status_code=201)
async def upload_source(client_id: int, report_id: int, kind: str = Form(...), file: UploadFile = File(...),
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(require_module("digests", write=True))):
    client = await _client(db, client_id)
    report, config = await _load(db, client_id, report_id, lock=True)
    content = await file.read(service.MAX_SOURCE_BYTES + 1)
    try:
        await service.add_source(db, client, report, kind=kind, filename=file.filename or "archivo",
                                 content_type=file.content_type or "", content=content, actor=user)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.delete("/reports/{report_id}/sources/{source_id}")
async def delete_source(client_id: int, report_id: int, source_id: int, db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_module("digests", write=True))):
    client = await _client(db, client_id)
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.remove_source(db, client, report, source_id)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.get("/reports/{report_id}/sources/{source_id}")
async def download_source(client_id: int, report_id: int, source_id: int, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_module("digests"))):
    report, _config_row = await _load(db, client_id, report_id)
    row = next((s for s in await service.list_sources(db, report.id, content=True) if s.id == source_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return Response(content=row.content, **stored_file_response_args(row.filename, row.content_type))


@router.post("/reports/{report_id}/draft", status_code=202)
async def draft(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                user: User = Depends(require_module("digests", write=True))):
    """Redacta en segundo plano todos los textos con IA; la versión dice cuándo acaba (`ai_status`)."""
    ai_limiter.check(user.id, 5, 300)
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        tone = await service.tone_for(db, report)
        await service.start_draft(db, report, template=config.template, tone=tone)
    except service.ReportError as exc:
        raise _http(exc) from exc
    return _summary(report)


@router.post("/reports/{report_id}/generate")
async def generate(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_module("digests", write=True))):
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.generate(db, report, template=config.template, actor=user)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": (f"attachment; filename=\"{filename.encode('ascii', 'ignore').decode()}\"; "
                                f"filename*=UTF-8''{quote(filename, safe='')}"),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })


@router.get("/reports/{report_id}/files/{kind}")
async def download_file(client_id: int, report_id: int, kind: str, db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_module("digests"))):
    """`html` (con el PDF incrustado), `pdf` o `datos` (datos.json + roadmap.json para rehacerlo)."""
    report, _config_row = await _load(db, client_id, report_id, files=kind in ("html", "pdf"))
    stem = report.file_stem or f"informe-{report.period_start.isoformat()}"
    if kind == "datos":
        payload = json.dumps({"datos": report.datos, "roadmap": report.roadmap, "inputs": report.inputs},
                             ensure_ascii=False, indent=1).encode("utf-8")
        return _download(payload, f"{stem}_datos.json", "application/json")
    if kind not in ("html", "pdf"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    content = report.html if kind == "html" else report.pdf
    if not content:
        raise HTTPException(status_code=404, detail="Esta versión aún no se ha generado")
    return _download(content, f"{stem}.{kind}", "text/html" if kind == "html" else "application/pdf")


@router.post("/reports/{report_id}/deliver")
async def deliver(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                  user: User = Depends(require_module("digests", write=True))):
    report, config = await _load(db, client_id, report_id, lock=True)
    try:
        await service.deliver(db, report, actor=user)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, report, config.template)


@router.post("/reports/{report_id}/new-version", status_code=201)
async def new_version(client_id: int, report_id: int, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_module("digests", write=True))):
    report, config = await _load(db, client_id, report_id)
    try:
        copy_row = await service.new_version(db, report, actor=user)
    except service.ReportError as exc:
        raise _http(exc) from exc
    await db.commit()
    return await _detail(db, copy_row, config.template)
