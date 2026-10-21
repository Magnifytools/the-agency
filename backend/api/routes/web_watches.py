"""Webs: URLs vigiladas por cambios (portado de ``Vigil/backend/app/api/watches.py``).

Permisos (módulo ``web``): leer = ver; escribir = dar de alta, cambiar,
archivar, "Comprobar ahora" y "Probar esta configuración".

Ningún barrido corre dentro de una petición (regla 4 de Vigil): "Comprobar"
deja ``check_requested_at`` y el job ``web_sweep`` lo recoge en menos de un
minuto. Lo único que pide la web del cliente desde la petición es la
previsualización (UNA URL, 20 s como mucho) y la lectura del sitemap (60 s),
ambas con límite por usuario.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_client_or_404, require_module
from backend.config import settings
from backend.core.rate_limiter import web_preview_limiter
from backend.db.database import get_db
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, User, WebChange, WebSnapshot, WebSweepRun, WebWatch, WebWatchState,
)
from backend.schemas.web import (
    SitemapImport, WatchBulkCreate, WatchCreate, WatchPreview, WatchUpdate, normalize_target_url,
)
from backend.services.web import sweep
from backend.services.web.changes_views import change_view, items_by_change, watch_view
from backend.services.web.extractor import CaptureConfig, drop_always, extract_text, parse, prepare
from backend.services.web.safe_http import fetch
from backend.services.web.sitemap import TOTAL_TIMEOUT_S, fetch_sitemap_urls
from backend.services.web.uptime import cause_label
from backend.services.web.uptime_views import iso

router = APIRouter(tags=["web"])

MODULE = "web"
MAX_BULK = 500
PREVIEW_TIMEOUT_S = 20.0
_PREVIEWS_PER_MINUTE = 6


def _monitored(client: Client) -> bool:
    return client.status == ClientStatus.active and not client.is_internal


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="URL no encontrada")


async def _watch_or_404(db: AsyncSession, watch_id: str) -> WebWatch:
    watch = await db.get(WebWatch, _uuid(watch_id))
    if watch is None:
        raise HTTPException(status_code=404, detail="URL no encontrada")
    return watch


async def _view(db: AsyncSession, watch: WebWatch) -> dict:
    state = await db.get(WebWatchState, watch.id, populate_existing=True)
    return watch_view(watch, state, checking=bool(state and state.checking_since))


async def _insert_urls(db: AsyncSession, client_id: int, urls: list[str], flags: dict, user_id: int,
                       source: str) -> dict:
    """Alta en bloque idempotente. Devuelve un recuento honesto de cada URL."""
    created = duplicates = restored = 0
    invalid: list[dict] = []
    existing = {w.url: w for w in (await db.scalars(select(WebWatch).where(WebWatch.client_id == client_id))).all()}
    seen: set[str] = set()
    now = datetime.now(UTC)
    for raw in urls[:MAX_BULK]:
        try:
            url = normalize_target_url(raw)
        except ValueError as exc:
            invalid.append({"url": str(raw)[:200], "reason": str(exc)})
            continue
        if url in seen:
            duplicates += 1
            continue
        seen.add(url)
        current = existing.get(url)
        if current is not None:
            if current.archived_at is not None:
                # Archivada = se recupera con su historial, no se crea otra.
                current.archived_at, current.is_active, current.updated_at = None, True, now
                restored += 1
            else:
                duplicates += 1
            continue
        db.add(WebWatch(client_id=client_id, url=url, source=source, created_by=user_id,
                        created_at=now, updated_at=now, **flags))
        created += 1
    await db.commit()
    return {"created": created, "restored": restored, "skipped_duplicates": duplicates, "invalid": invalid,
            "truncated": len(urls) > MAX_BULK}


# ── Listado y alta ───────────────────────────────────────────────────


@router.get("/api/clients/{client_id}/web/watches")
async def list_watches(
    client_id: int,
    q: str | None = Query(None, max_length=200),
    only_errors: bool = False,
    only_changed: bool = False,
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    client = await get_client_or_404(client_id, db)
    query = (select(WebWatch, WebWatchState).outerjoin(WebWatchState, WebWatchState.watch_id == WebWatch.id)
             .where(WebWatch.client_id == client_id))
    if not include_archived:
        query = query.where(WebWatch.archived_at.is_(None))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(WebWatch.url.ilike(pattern), func.coalesce(WebWatch.label, "").ilike(pattern)))
    if only_errors:
        query = query.where(WebWatchState.last_error.is_not(None))
    if only_changed:
        query = query.where(WebWatchState.last_changed_at.is_not(None))
    query = query.order_by(WebWatchState.last_changed_at.desc().nulls_last(), WebWatch.url)
    rows = (await db.execute(query)).all()
    run_live = await _running(db, client_id)
    cutoff = sweep.stale_mark_cutoff()
    return {
        "enabled": settings.WEB_SWEEP_ENABLED,
        "monitored": _monitored(client),
        "watches": [watch_view(w, s, checking=bool(run_live and s and s.checking_since and s.checking_since >= cutoff))
                    for w, s in rows],
    }


@router.post("/api/clients/{client_id}/web/watches", status_code=status.HTTP_201_CREATED)
async def create_watch(
    client_id: int,
    body: WatchCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    await get_client_or_404(client_id, db)
    existing = await db.scalar(select(WebWatch).where(WebWatch.client_id == client_id, WebWatch.url == body.url))
    now = datetime.now(UTC)
    if existing is not None:
        if existing.archived_at is None:
            raise HTTPException(status_code=409, detail="Esa URL ya está dada de alta")
        existing.archived_at, existing.is_active, existing.updated_at = None, True, now
        await db.commit()
        return await _view(db, existing)
    watch = WebWatch(client_id=client_id, url=body.url, label=body.label, content_selector=body.content_selector,
                     watch_seo=body.watch_seo, watch_content=body.watch_content, watch_links=body.watch_links,
                     watch_html=body.watch_html, source="manual", created_by=user.id, created_at=now,
                     updated_at=now)
    db.add(watch)
    await db.commit()
    return await _view(db, watch)


@router.post("/api/clients/{client_id}/web/watches/bulk")
async def create_bulk(
    client_id: int,
    body: WatchBulkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Alta en bloque desde una lista pegada o un CSV (hasta 500 por vez)."""
    await get_client_or_404(client_id, db)
    flags = body.model_dump(include={"watch_seo", "watch_content", "watch_links", "watch_html"})
    return await _insert_urls(db, client_id, body.urls, flags, user.id, body.source)


@router.post("/api/clients/{client_id}/web/watches/import-sitemap")
async def import_sitemap(
    client_id: int,
    body: SitemapImport,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Importa URLs de un sitemap (índices anidados incluidos). ``lastmod`` se
    ignora a propósito: es poco fiable y confiar en él saltaría páginas que sí
    cambiaron."""
    web_preview_limiter.check(user.id, _PREVIEWS_PER_MINUTE, 60)
    await get_client_or_404(client_id, db)
    web = await db.get(ClientWebSettings, client_id)
    user_agent = web.user_agent if web else None
    await db.commit()  # nada de transacción abierta mientras se espera a la web
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_S):
            urls, has_more = await fetch_sitemap_urls(body.sitemap_url, limit=body.limit, user_agent=user_agent)
    except TimeoutError:
        raise HTTPException(status_code=400, detail="El sitemap tarda demasiado en responder")
    except Exception as exc:  # noqa: BLE001 — el motivo vuelve al usuario
        raise HTTPException(status_code=400, detail=f"No se pudo leer el sitemap: {str(exc)[:200]}")
    if body.include:
        urls = [u for u in urls if re.search(body.include, u)]
    if body.exclude:
        urls = [u for u in urls if not re.search(body.exclude, u)]
    result = await _insert_urls(db, client_id, urls[: body.limit],
                                {"watch_seo": True, "watch_content": True}, user.id, "sitemap")
    result["found_in_sitemap"] = len(urls)
    # El sitemap tiene MÁS de lo que se ha traído: hay que decirlo, o "200 en el
    # sitemap" se lee como "el site entero son 200 páginas".
    result["sitemap_has_more"] = has_more
    result["limit_applied"] = body.limit
    return result


# ── Una URL ──────────────────────────────────────────────────────────


@router.get("/api/web/watches/{watch_id}")
async def get_watch(
    watch_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    watch = await _watch_or_404(db, watch_id)
    changes = list((await db.scalars(
        select(WebChange).where(WebChange.watch_id == watch.id)
        .order_by(WebChange.detected_at.desc()).limit(50)
    )).all())
    items = await items_by_change(db, [c.id for c in changes])
    return {
        "watch": await _view(db, watch),
        "changes": [change_view(c, url=watch.url, label=watch.label, items=items.get(c.id)) for c in changes],
    }


@router.patch("/api/web/watches/{watch_id}")
async def patch_watch(
    watch_id: str,
    body: WatchUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    watch = await _watch_or_404(db, watch_id)
    sent = body.model_fields_set
    for key in ("is_active", "muted", "watch_seo", "watch_content", "watch_links", "watch_html"):
        if key in sent and getattr(body, key) is not None:
            setattr(watch, key, getattr(body, key))
    for key in ("label", "content_selector", "ignore_selectors", "ignore_regexes"):
        if key in sent:
            setattr(watch, key, getattr(body, key))
    if sent:
        watch.updated_at = datetime.now(UTC)
    if "content_selector" in sent:
        # El aviso de "la sección ya no existe" hablaba del selector anterior.
        await db.execute(update(WebWatchState).where(WebWatchState.watch_id == watch.id).values(scope_missed=False))
    await db.commit()
    return await _view(db, watch)


@router.post("/api/web/watches/{watch_id}/archive")
async def archive_watch(
    watch_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    """Fuera de la lista y del barrido, con su historial de cambios intacto.
    Sus cambios sin revisar dejan de avisar. Se recupera con ``/restore`` o
    volviendo a darla de alta."""
    watch = await _watch_or_404(db, watch_id)
    if watch.archived_at is None:
        now = datetime.now(UTC)
        watch.archived_at, watch.is_active, watch.check_requested_at, watch.updated_at = now, False, None, now
        await db.commit()
    return await _view(db, watch)


@router.post("/api/web/watches/{watch_id}/restore")
async def restore_watch(
    watch_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    watch = await _watch_or_404(db, watch_id)
    if watch.archived_at is not None:
        watch.archived_at, watch.is_active, watch.updated_at = None, True, datetime.now(UTC)
        await db.commit()
    return await _view(db, watch)


# ── Comprobar ────────────────────────────────────────────────────────


async def _request_check(db: AsyncSession, client: Client, watch_ids: list[uuid.UUID]) -> datetime:
    if not _monitored(client):
        raise HTTPException(status_code=409, detail="El cliente no está activo: sus webs no se comprueban")
    now = datetime.now(UTC)
    await db.execute(update(WebWatch).where(WebWatch.id.in_(watch_ids)).values(check_requested_at=now))
    await db.commit()
    return now


@router.post("/api/web/watches/{watch_id}/check", status_code=status.HTTP_202_ACCEPTED)
async def check_now(
    watch_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    """Comprobación de una URL. 202: la hace el job ``web_sweep`` en menos de un
    minuto (si está encendido; ``enabled`` lo dice)."""
    watch = await _watch_or_404(db, watch_id)
    if watch.archived_at is not None or not watch.is_active:
        raise HTTPException(status_code=409, detail="La URL está pausada o archivada")
    client = await get_client_or_404(watch.client_id, db)
    requested = await _request_check(db, client, [watch.id])
    return {"status": "accepted", "watch_id": str(watch.id), "requested_at": iso(requested),
            "enabled": settings.WEB_SWEEP_ENABLED}


@router.post("/api/clients/{client_id}/web/watches/check-all", status_code=status.HTTP_202_ACCEPTED)
async def check_all(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE, write=True)),
):
    """Todas las URLs activas del cliente: al terminar manda el resumen a su Slack."""
    client = await get_client_or_404(client_id, db)
    ids = list((await db.scalars(select(WebWatch.id).where(
        WebWatch.client_id == client_id, sweep.watched_clause(),
    ))).all())
    if not ids:
        raise HTTPException(status_code=400, detail="No hay URLs activas que comprobar")
    requested = await _request_check(db, client, ids)
    return {"status": "accepted", "watches": len(ids), "requested_at": iso(requested),
            "enabled": settings.WEB_SWEEP_ENABLED}


async def _running(db: AsyncSession, client_id: int) -> WebSweepRun | None:
    run = await db.scalar(select(WebSweepRun).where(WebSweepRun.client_id == client_id)
                          .order_by(WebSweepRun.started_at.desc()).limit(1))
    return run if run is not None and run.status == "running" else None


@router.get("/api/clients/{client_id}/web/watches/progress")
async def progress(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """¿Se está comprobando algo ahora? Sin esto, "Comprobar" no daba señal y no
    se distinguía "trabajando" de "roto". Dos filtros contra el spinner eterno
    (lección 0ter de Vigil): sin barrido vivo no hay nada "comprobándose", y una
    marca de más de 45 min tampoco cuenta."""
    await get_client_or_404(client_id, db)
    last = await db.scalar(select(WebSweepRun).where(WebSweepRun.client_id == client_id)
                           .order_by(WebSweepRun.started_at.desc()).limit(1))
    running = last is not None and last.status == "running"
    checking: list[str] = []
    if running:
        checking = [str(i) for i in (await db.scalars(select(WebWatchState.watch_id).where(
            WebWatchState.client_id == client_id, WebWatchState.checking_since >= sweep.stale_mark_cutoff(),
        ))).all()]
    queued = [str(i) for i in (await db.scalars(select(WebWatch.id).where(
        WebWatch.client_id == client_id, WebWatch.check_requested_at.is_not(None), sweep.watched_clause(),
    ))).all()]
    return {
        "enabled": settings.WEB_SWEEP_ENABLED,
        "is_running": running,
        "checking": checking,
        # Pedidas y aún no recogidas por el job (si está apagado, se quedan aquí).
        "queued": queued,
        "last_run": None if last is None else {
            "id": str(last.id), "status": last.status, "trigger": last.trigger,
            "watches_total": last.watches_total, "watches_done": last.watches_done,
            "watches_error": last.watches_error, "changes_found": last.changes_found,
            "started_at": iso(last.started_at), "finished_at": iso(last.finished_at),
        },
    }


# ── Previsualizar ────────────────────────────────────────────────────


def _measure(raw: str, cfg: CaptureConfig) -> dict:
    """Lo que se vigilaría DE VERDAD con esa configuración (misma secuencia que el
    barrido: ``prepare`` + ``extract_text``). CPU: va en un hilo."""
    def words(nodes) -> int:
        return len(" ".join(n.text_content() for n in nodes).split())

    # Texto visible de la página ANTES de nuestra configuración (sin el JS inline:
    # contarlo haría creer que se descarta media página).
    full = parse(raw)
    drop_always(full)
    total = words([full])
    pruned = []
    for selector in cfg.ignore_selectors:
        try:
            nodes = full.cssselect(selector)
        except Exception:  # noqa: BLE001
            pruned.append({"selector": selector, "valid": False, "nodes": 0, "words": 0})
            continue
        pruned.append({"selector": selector, "valid": True, "nodes": len(nodes), "words": words(nodes)})
    nodes, scoped = prepare(parse(raw), cfg)
    text = extract_text(nodes, cfg, acotado=scoped)
    return {
        "page_words": total,
        "watched_words": len(text.split()),
        "selector": cfg.content_selector,
        # False con selector puesto = hoy no casa nada y se vigila la página entera.
        "selector_matches": scoped,
        "section_nodes": len(nodes) if scoped else 0,
        # Lo que se lleva cada selector de poda: `[aria-live]` se comía 1.039 palabras.
        "ignored": pruned,
        "sample": text[:600],
    }


@router.post("/api/web/watches/{watch_id}/preview")
async def preview_watch(
    watch_id: str,
    body: WatchPreview,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_module(MODULE, write=True)),
):
    """Descarga la URL y dice QUÉ se vigilaría con esa configuración. Una
    petición (20 s como mucho), no un barrido; no toca la base de datos."""
    web_preview_limiter.check(user.id, _PREVIEWS_PER_MINUTE, 60)
    watch = await _watch_or_404(db, watch_id)
    cfg_client = sweep.effective_settings(await db.get(ClientWebSettings, watch.client_id))
    saved = sweep.effective_config(watch, cfg_client)
    sent = body.model_fields_set
    cfg = CaptureConfig(
        content_selector=(body.content_selector if "content_selector" in sent else saved.content_selector) or None,
        ignore_selectors=(tuple(body.ignore_selectors or ()) if "ignore_selectors" in sent
                          else saved.ignore_selectors),
        ignore_regexes=(tuple(body.ignore_regexes or ()) if "ignore_regexes" in sent else saved.ignore_regexes),
    )
    url, user_agent = watch.url, cfg_client.user_agent
    timeout = min(PREVIEW_TIMEOUT_S, float(cfg_client.request_timeout_s))
    await db.commit()  # nada de transacción abierta mientras se espera a la web
    result = await fetch(url, user_agent=user_agent, timeout=timeout, max_bytes=sweep.MAX_BODY_BYTES)
    if not sweep.fetch_ok(result):
        raise HTTPException(status_code=502,
                            detail=f"No se pudo descargar la página: {cause_label(result.error) or 'sin respuesta'}")
    measured = await asyncio.to_thread(_measure, sweep.decode_body(result), cfg)
    return {"url": url, "status_code": result.status_code, "final_url": result.final_url, **measured}


@router.get("/api/web/watches/{watch_id}/history")
async def watch_history(
    watch_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module(MODULE)),
):
    """Capturas guardadas (sólo las hay cuando algo cambió)."""
    watch = await _watch_or_404(db, watch_id)
    rows = (await db.execute(
        select(WebSnapshot.id, WebSnapshot.captured_at, WebSnapshot.status_code, WebSnapshot.byte_size,
               WebSnapshot.content_hash, WebSnapshot.html_hash, WebSnapshot.is_pinned,
               (WebSnapshot.html_gz.is_not(None)).label("has_html"))
        .where(WebSnapshot.watch_id == watch.id).order_by(WebSnapshot.captured_at.desc()).limit(limit)
    )).all()
    return {"snapshots": [{
        "id": str(r.id), "captured_at": iso(r.captured_at), "status_code": r.status_code, "byte_size": r.byte_size,
        "content_hash": r.content_hash, "html_hash": r.html_hash, "is_pinned": r.is_pinned, "has_html": r.has_html,
    } for r in rows]}
