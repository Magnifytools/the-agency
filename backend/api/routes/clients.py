from __future__ import annotations
import logging
import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy import select, func, delete, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    Client, ClientStatus, Task, TimeEntry, User,
    Project, ProjectPhase, ProjectEvidence,
    ClientContact, ClientResource, BillingEvent,
    CommunicationLog, WeeklyDigest, Invoice, InvoiceItem,
    PMInsight, GrowthIdea, Proposal, Event, Lead,
    GeneratedReport, Income, Expense, HoldedInvoiceCache, ClientDocument,
    BalanceSnapshot,
)
from backend.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientDocumentResponse
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module, require_admin
from backend.services.client_health import compute_health, compute_health_batch
from backend.api.utils.db_helpers import safe_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("", response_model=PaginatedResponse[ClientResponse])
async def list_clients(
    status_filter: Optional[ClientStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    base = select(Client)
    if status_filter:
        base = base.where(Client.status == status_filter)
    else:
        base = base.where(Client.status != ClientStatus.finished)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    query = base.order_by(Client.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)

    return PaginatedResponse(items=result.scalars().all(), total=total, page=page, page_size=page_size)


_CLIENT_EXTRACT_PROMPT = """Analiza este texto de contexto sobre un cliente y extrae la información relevante.
Responde SOLO con un JSON válido con los campos que puedas extraer (omite los que no aparezcan):
{
  "name": "nombre del cliente/empresa principal (el cliente final, no intermediarios)",
  "company": "nombre de la empresa (puede ser igual a name)",
  "email": "email de contacto principal o null",
  "phone": "teléfono de contacto principal o null",
  "website": "URL del site/dominio del proyecto o del cliente (ej: https://www.ejemplo.com) o null",
  "contract_type": "monthly si es recurrente/retención, one_time si es puntual",
  "monthly_budget": importe mensual numérico o null (solo si es fijo; si es variable, dejarlo null)",
  "notes": "resumen breve de la relación y contexto importante (2-3 frases)",
  "business_model": "sector/modelo de negocio del cliente (ej: ecommerce, saas, igaming, media, fintech, etc.) o null",
  "is_intermediary_deal": true si hay una agencia intermediaria entre nosotros y el cliente final,
  "intermediary_name": "nombre de la agencia intermediaria o null",
  "context": "resumen ejecutivo completo: quién es el cliente, cómo llegó, qué se ha hecho, qué se ha prometido, particularidades del trato",
  "contacts": [
    {
      "name": "nombre completo de la persona",
      "email": "email o null",
      "phone": "teléfono o null",
      "position": "cargo/rol o null",
      "company": "empresa a la que pertenece (si diferente del cliente) o null",
      "is_primary": true solo para el contacto principal de comunicación,
      "notes": "contexto relevante sobre esta persona (preferencias, idioma, etc.) o null",
      "language": "es o en según el idioma de comunicación con esta persona, o null"
    }
  ],
  "project": {
    "name": "nombre del proyecto/servicio activo o más reciente (breve, máx 60 chars)",
    "description": "resumen del alcance en 2-3 frases",
    "project_type": "uno de: seo_audit | content_strategy | linkbuilding | technical_seo | custom",
    "is_recurring": true si es servicio recurrente/mensual,
    "pricing_model": "uno de: monthly | per_piece | hourly | project (o null)",
    "unit_price": precio por unidad numérico o null,
    "unit_label": "etiqueta de la unidad (pieza, artículo, hora, etc.) o null",
    "scope": "descripción detallada del alcance/scope aprobado del proyecto",
    "monthly_fee": importe mensual recurrente que factura este proyecto o null,
    "budget_amount": importe total del proyecto o null,
    "start_date": "YYYY-MM-DD o null",
    "target_end_date": "YYYY-MM-DD o null"
  }
}
Extrae como contactos SOLO personas del lado del cliente, intermediarios o stakeholders externos.
NO incluyas personas de nuestro propio equipo (los remitentes/destinatarios del lado "nosotros", como David, Nacho u otros del equipo SEO/Magnify).
Si no hay información suficiente para el proyecto, omite el campo "project".
Si no se mencionan personas externas con nombre, omite el campo "contacts".
Sin texto adicional. Solo el JSON."""


class ProjectExtractInline(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    is_recurring: bool = False
    pricing_model: Optional[str] = None
    monthly_fee: Optional[float] = None
    unit_price: Optional[float] = None
    unit_label: Optional[str] = None
    scope: Optional[str] = None
    budget_amount: Optional[float] = None
    start_date: Optional[str] = None
    target_end_date: Optional[str] = None


class ContactExtractInline(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    company: Optional[str] = None
    is_primary: bool = False
    notes: Optional[str] = None
    language: Optional[str] = None


class ClientExtract(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    contract_type: Optional[str] = None
    monthly_budget: Optional[float] = None
    notes: Optional[str] = None
    business_model: Optional[str] = None
    is_intermediary_deal: bool = False
    intermediary_name: Optional[str] = None
    context: Optional[str] = None
    contacts: Optional[list[ContactExtractInline]] = None
    project: Optional[ProjectExtractInline] = None


@router.post("/extract-context", response_model=ClientExtract)
async def extract_client_context(
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    _: User = Depends(require_module("clients", write=True)),
):
    """Extract client info from a text file (.txt/.md) or pasted raw text."""
    from backend.services.ai_utils import get_anthropic_client, parse_claude_json

    text_content = ""
    if file and file.filename:
        ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
        if ext not in ("txt", "md"):
            raise HTTPException(400, "Solo se aceptan archivos .txt o .md")
        raw = await file.read()
        if len(raw) > 1 * 1024 * 1024:
            raise HTTPException(400, "El archivo no puede superar 1MB")
        text_content = raw.decode("utf-8", errors="replace")
    elif raw_text and raw_text.strip():
        text_content = raw_text.strip()
    else:
        raise HTTPException(400, "Debes subir un archivo o pegar texto")

    client = get_anthropic_client()
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"Documento de contexto:\n\n{text_content}\n\n---\n\n{_CLIENT_EXTRACT_PROMPT}"},
        ]}],
    )
    try:
        data = parse_claude_json(message)
        return ClientExtract(**data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"No se pudieron extraer los datos: {e}")


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    client = Client(**body.model_dump())
    db.add(client)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un cliente con esos datos")
    except Exception as e:
        await db.rollback()
        logger.error("Error creando cliente: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await safe_refresh(db, client, log_context="clients")
    return client


@router.get("/health-scores")
async def list_health_scores(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Health scores for all active clients."""
    try:
        result = await db.execute(
            select(Client).where(Client.status == ClientStatus.active).order_by(Client.name)
        )
        clients = result.scalars().all()
        scores = await compute_health_batch(clients, db)
        # Sort by score ascending (worst first)
        scores.sort(key=lambda s: s["score"])
        return scores
    except Exception as e:
        logger.error("Error computing batch health scores: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando health scores")


@router.get("/{client_id}/health")
async def get_client_health(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Health score for a single client."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        return await compute_health(client, db)
    except Exception as e:
        logger.error("Error computing health for client %s: %s", client_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error calculando health score")


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    _UPDATABLE_CLIENT_FIELDS = {
        "name", "email", "phone", "company", "website", "contract_type",
        "monthly_budget", "status", "notes", "is_internal", "ga4_property_id",
        "gsc_url", "billing_cycle", "billing_day", "next_invoice_date",
        "last_invoiced_date", "engine_project_id", "business_model", "aov",
        "conversion_rate", "ltv", "seo_maturity_level", "context",
        "cif", "vat_number",
    }
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in _UPDATABLE_CLIENT_FIELDS:
            setattr(client, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto al actualizar cliente")
    except Exception as e:
        await db.rollback()
        logger.error("Error actualizando cliente %d: %s", client_id, e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
    await safe_refresh(db, client, log_context="clients")
    return client


@router.delete("/{client_id}/hard", status_code=204)
async def hard_delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Protect against deleting clients with financial records (legal retention)
    income_count = (await db.execute(
        select(func.count()).where(Income.client_id == client_id)
    )).scalar() or 0
    invoice_count = (await db.execute(
        select(func.count()).where(Invoice.client_id == client_id)
    )).scalar() or 0
    if income_count > 0 or invoice_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: el cliente tiene {income_count} ingresos y {invoice_count} facturas registradas. "
                   "Use desactivar (soft delete) para preservar el historial financiero.",
        )

    # Collect IDs needed for cascade operations
    project_ids = list((await db.execute(
        select(Project.id).where(Project.client_id == client_id)
    )).scalars())
    task_ids = list((await db.execute(
        select(Task.id).where(Task.client_id == client_id)
    )).scalars())
    invoice_ids = list((await db.execute(
        select(Invoice.id).where(Invoice.client_id == client_id)
    )).scalars())

    # Step 1: Nullify nullable FKs referencing this client's data
    await db.execute(update(Proposal).where(Proposal.client_id == client_id).values(client_id=None))
    if project_ids:
        await db.execute(update(Proposal).where(Proposal.converted_project_id.in_(project_ids)).values(converted_project_id=None))

    await db.execute(update(Event).where(Event.client_id == client_id).values(client_id=None))
    if project_ids:
        await db.execute(update(Event).where(Event.project_id.in_(project_ids)).values(project_id=None))

    await db.execute(update(Lead).where(Lead.converted_client_id == client_id).values(converted_client_id=None))

    await db.execute(update(GeneratedReport).where(GeneratedReport.client_id == client_id).values(client_id=None))
    if project_ids:
        await db.execute(update(GeneratedReport).where(GeneratedReport.project_id.in_(project_ids)).values(project_id=None))

    await db.execute(update(Income).where(Income.client_id == client_id).values(client_id=None))
    await db.execute(update(HoldedInvoiceCache).where(HoldedInvoiceCache.client_id == client_id).values(client_id=None))

    # PMInsight: delete rows associated with this client, its tasks, or its projects
    pm_conditions = [PMInsight.client_id == client_id]
    if task_ids:
        pm_conditions.append(PMInsight.task_id.in_(task_ids))
    if project_ids:
        pm_conditions.append(PMInsight.project_id.in_(project_ids))
    await db.execute(delete(PMInsight).where(or_(*pm_conditions)))

    # GrowthIdea: nullify task/project references
    if task_ids:
        await db.execute(update(GrowthIdea).where(GrowthIdea.task_id.in_(task_ids)).values(task_id=None))
    if project_ids:
        await db.execute(update(GrowthIdea).where(GrowthIdea.project_id.in_(project_ids)).values(project_id=None))

    # Task self-referential depends_on
    if task_ids:
        await db.execute(update(Task).where(Task.depends_on.in_(task_ids)).values(depends_on=None))

    # InvoiceItem.task_id (nullable)
    if task_ids:
        await db.execute(update(InvoiceItem).where(InvoiceItem.task_id.in_(task_ids)).values(task_id=None))

    # Step 2: Delete rows that depend on tasks/projects/invoices (children first)
    if task_ids:
        await db.execute(delete(TimeEntry).where(TimeEntry.task_id.in_(task_ids)))
    if invoice_ids:
        await db.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids)))
    if project_ids:
        await db.execute(delete(ProjectEvidence).where(ProjectEvidence.project_id.in_(project_ids)))

    # Step 3: Delete tables with NOT NULL client_id (in dependency order)
    # CommunicationLog before ClientContact (contact_id FK)
    await db.execute(delete(CommunicationLog).where(CommunicationLog.client_id == client_id))
    await db.execute(delete(ClientContact).where(ClientContact.client_id == client_id))
    await db.execute(delete(ClientResource).where(ClientResource.client_id == client_id))
    await db.execute(delete(BillingEvent).where(BillingEvent.client_id == client_id))
    await db.execute(delete(WeeklyDigest).where(WeeklyDigest.client_id == client_id))
    # Task before ProjectPhase and Project
    await db.execute(delete(Task).where(Task.client_id == client_id))
    if project_ids:
        await db.execute(delete(ProjectPhase).where(ProjectPhase.project_id.in_(project_ids)))
    await db.execute(delete(Project).where(Project.client_id == client_id))
    await db.execute(delete(Invoice).where(Invoice.client_id == client_id))

    # Step 4: Delete the client
    await db.delete(client)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar: el cliente tiene registros asociados que no se pudieron borrar",
        )


@router.delete("/{client_id}", response_model=ClientResponse)
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    client.status = ClientStatus.finished
    await db.commit()
    await safe_refresh(db, client, log_context="clients")
    return client


@router.get("/{client_id}/summary")
async def get_client_summary(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Fetch tasks with relationships needed for _task_to_response
    from sqlalchemy.orm import selectinload
    tasks_result = await db.execute(
        select(Task).options(
            selectinload(Task.client),
            selectinload(Task.category),
            selectinload(Task.assigned_user),
            selectinload(Task.project),
            selectinload(Task.phase),
        ).where(Task.client_id == client_id).order_by(Task.created_at.desc())
    )
    tasks = tasks_result.scalars().unique().all()

    # Aggregate time via subquery (avoids building huge IN list)
    task_ids_subq = select(Task.id).where(Task.client_id == client_id).scalar_subquery()
    time_result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.task_id.in_(task_ids_subq),
            TimeEntry.minutes.isnot(None),
        )
    )
    total_tracked_minutes = time_result.scalar()

    total_estimated = sum(t.estimated_minutes or 0 for t in tasks)
    total_actual = sum(t.actual_minutes or 0 for t in tasks)

    from backend.schemas.task import TaskResponse
    from backend.api.routes.tasks import _task_to_response

    return {
        "client": ClientResponse.model_validate(client),
        "tasks": [_task_to_response(t) for t in tasks],
        "total_tasks": len(tasks),
        "total_estimated_minutes": total_estimated,
        "total_actual_minutes": total_actual,
        "total_tracked_minutes": total_tracked_minutes,
    }


@router.get("/{client_id}/recent-time-entries")
async def get_recent_time_entries(
    client_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    """Recent time entries for a client, single query instead of N parallel fetches."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .options(selectinload(TimeEntry.task), selectinload(TimeEntry.user))
        .where(Task.client_id == client_id, TimeEntry.minutes.isnot(None))
        .order_by(TimeEntry.date.desc())
        .limit(limit)
    )
    entries = result.scalars().unique().all()
    return [
        {
            "id": e.id,
            "date": e.date.isoformat() if e.date else None,
            "minutes": e.minutes,
            "notes": e.notes,
            "task_title": e.task.title if e.task else None,
            "user_name": e.user.full_name if e.user else None,
        }
        for e in entries
    ]


@router.post("/{client_id}/ai-advice")
async def get_ai_advice(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    """Get AI-generated recommendations for a client."""
    from backend.services.client_advisor import get_client_advice
    try:
        recommendations = await get_client_advice(db, client_id)
        return {"recommendations": recommendations}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{client_id}/documents", response_model=list[ClientDocumentResponse])
async def list_documents(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(
        select(ClientDocument).where(ClientDocument.client_id == client_id)
        .order_by(ClientDocument.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{client_id}/documents", response_model=ClientDocumentResponse, status_code=201)
async def upload_document(
    client_id: int,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    _ALLOWED_MIME_TYPES = {
        "application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain", "text/csv",
        "application/zip",
    }
    _ALLOWED_EXTENSIONS = {
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".doc", ".docx", ".xls", ".xlsx",
        ".txt", ".csv", ".zip",
    }
    filename = file.filename or ""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Extensión no permitida: {ext or '(sin extensión)'}")
    if not file.content_type or file.content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Tipo de archivo no permitido: {file.content_type or '(sin tipo)'}")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "Archivo demasiado grande (máx 20 MB)")
    doc = ClientDocument(
        client_id=client_id,
        name=file.filename or "documento",
        description=description,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        content=content,
    )
    db.add(doc)
    await db.commit()
    await safe_refresh(db, doc, log_context="clients")
    return doc


@router.get("/{client_id}/documents/{doc_id}/download")
async def download_document(
    client_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients")),
):
    result = await db.execute(
        select(ClientDocument).where(ClientDocument.id == doc_id, ClientDocument.client_id == client_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    return Response(
        content=doc.content,
        media_type=doc.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.name, safe='')}"},
    )


@router.delete("/{client_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    client_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("clients", write=True)),
):
    result = await db.execute(
        select(ClientDocument).where(ClientDocument.id == doc_id, ClientDocument.client_id == client_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    await db.delete(doc)
    await db.commit()


@router.get("/{client_id}/what-if", tags=["clients"])
async def what_if_lose_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_module("clients")),
):
    """Estimate financial impact of losing a client."""
    from datetime import date, timedelta

    # Check client exists
    r = await db.execute(select(Client).where(Client.id == client_id))
    client = r.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Average monthly revenue from this client (last 6 months)
    six_months_ago = date.today() - timedelta(days=180)
    r_inc = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.client_id == client_id, Income.date >= six_months_ago)
    )
    total_6m = float(r_inc.scalar() or 0)
    avg_monthly = round(total_6m / 6, 2)

    # Total company revenue last 6 months (for percentage)
    r_total = await db.execute(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.date >= six_months_ago)
    )
    total_company_6m = float(r_total.scalar() or 0)
    pct_of_total = round((total_6m / total_company_6m * 100) if total_company_6m > 0 else 0, 1)

    # Average monthly burn (last 3 months expenses)
    three_months_ago = date.today() - timedelta(days=90)
    r_burn = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.date >= three_months_ago)
    )
    burn_3m = float(r_burn.scalar() or 0)
    avg_burn = round(burn_3m / 3, 2)

    # Latest cash balance
    r_bal = await db.execute(
        select(BalanceSnapshot.amount).order_by(BalanceSnapshot.date.desc()).limit(1)
    )
    cash = float(r_bal.scalar() or 0)

    # Runway with vs without client
    if avg_burn > 0 and cash > 0:
        r_total_income_3m = await db.execute(
            select(func.coalesce(func.sum(Income.amount), 0))
            .where(Income.date >= three_months_ago)
        )
        total_income_3m = float(r_total_income_3m.scalar() or 0)
        avg_total_income = round(total_income_3m / 3, 2)
        avg_client_income = round(total_6m / 6, 2)

        net_monthly_without = (avg_total_income - avg_client_income) - avg_burn

        runway_current = round(cash / avg_burn, 1)
        if net_monthly_without < 0:
            runway_without = round(cash / abs(net_monthly_without), 1)
        else:
            runway_without = None  # sustainable
    else:
        runway_current = None
        runway_without = None

    return {
        "client_id": client_id,
        "client_name": client.name,
        "avg_monthly_revenue": avg_monthly,
        "annual_revenue_estimate": round(avg_monthly * 12, 2),
        "pct_of_total_revenue": pct_of_total,
        "runway_current": runway_current,
        "runway_without_client": runway_without,
        "monthly_impact": round(avg_monthly, 2),
    }


# ── Onboarding Intelligence ────────────────────────────────────


class IntelligenceRequest(BaseModel):
    url: str
    extra_context: str = ""


@router.post("/{client_id}/generate-intelligence")
async def generate_intelligence(
    client_id: int,
    body: IntelligenceRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Generate AI onboarding intelligence package for a client."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    from backend.services.onboarding_intelligence import generate_onboarding_intelligence
    intelligence = await generate_onboarding_intelligence(body.url, body.extra_context)

    client.onboarding_intelligence = intelligence
    await db.commit()

    return {"success": True, "intelligence": intelligence}
