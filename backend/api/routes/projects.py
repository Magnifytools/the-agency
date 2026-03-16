from __future__ import annotations
from typing import Optional

import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import Project, ProjectPhase, ProjectTemplateDB, Task, TaskStatus, PhaseStatus, ProjectStatus, TimeEntry
from backend.schemas.project import (
    ProjectCreate,
    ProjectExtract,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectPhaseCreate,
    ProjectPhaseUpdate,
    ProjectPhaseResponse,
    PROJECT_TEMPLATES,
)
from backend.schemas.pagination import PaginatedResponse
from backend.api.deps import get_current_user, require_module, require_admin
from backend.services.ai_utils import get_anthropic_client, parse_claude_json

EXTRACT_PROMPT = """Extrae la información de esta propuesta comercial y responde SOLO con un JSON válido:
{
  "name": "nombre del proyecto/servicio (breve, máx 60 chars)",
  "description": "resumen del alcance en 2-3 frases",
  "project_type": "uno de: seo_audit | content_strategy | linkbuilding | technical_seo | custom",
  "is_recurring": true si es retención/servicio mensual, false si es proyecto puntual,
  "budget_amount": importe numérico sin símbolo o null,
  "start_date": "YYYY-MM-DD" o null,
  "target_end_date": "YYYY-MM-DD" o null,
  "client_name": "nombre de la empresa cliente",
  "pricing_model": "uno de: monthly | per_piece | hourly | project (o null si no aplica)",
  "unit_price": precio por unidad numérico o null,
  "unit_label": "etiqueta de la unidad (pieza, artículo, hora, etc.) o null",
  "scope": "descripción detallada del alcance/scope del proyecto"
}
Sin texto adicional. Solo el JSON."""

EXTRACT_TEXT_PROMPT = """Analiza este documento de contexto de proyecto y extrae la información relevante.
Responde SOLO con un JSON válido:
{
  "name": "nombre del proyecto/servicio (breve, máx 60 chars)",
  "description": "resumen del alcance en 2-3 frases",
  "project_type": "uno de: seo_audit | content_strategy | linkbuilding | technical_seo | custom",
  "is_recurring": true si es retención/servicio mensual, false si es proyecto puntual,
  "budget_amount": importe total numérico sin símbolo o null,
  "start_date": "YYYY-MM-DD" o null,
  "target_end_date": "YYYY-MM-DD" o null,
  "client_name": "nombre de la empresa cliente o null",
  "pricing_model": "uno de: monthly | per_piece | hourly | project (o null)",
  "unit_price": precio por unidad numérico o null,
  "unit_label": "etiqueta de la unidad (pieza, artículo, hora, etc.) o null",
  "scope": "descripción detallada del alcance/scope aprobado del proyecto"
}
Sin texto adicional. Solo el JSON."""

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_load_options():
    """Eager loading options for Project queries that need tasks/phases/client."""
    return [
        selectinload(Project.client),
        selectinload(Project.phases),
        selectinload(Project.tasks).selectinload(Task.assigned_user),
    ]


def calculate_progress(tasks: list) -> int:
    """Calculate project progress based on completed tasks."""
    if not tasks:
        return 0
    completed = sum(1 for t in tasks if t.status == TaskStatus.completed)
    return int((completed / len(tasks)) * 100)


def _build_project_response(project: Project, hours_used: Optional[float] = None) -> ProjectResponse:
    """Build a ProjectResponse from a Project model with eagerly loaded relationships."""
    task_count = len(project.tasks) if project.tasks else 0
    completed_count = (
        sum(1 for t in project.tasks if t.status == TaskStatus.completed)
        if project.tasks else 0
    )
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        is_recurring=project.is_recurring,
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        status=project.status.value,
        progress_percent=project.progress_percent,
        budget_hours=project.budget_hours,
        budget_amount=project.budget_amount,
        pricing_model=project.pricing_model,
        unit_price=float(project.unit_price) if project.unit_price is not None else None,
        unit_label=project.unit_label,
        scope=project.scope,
        client_id=project.client_id,
        client_name=project.client.name if project.client else None,
        phases=[
            ProjectPhaseResponse(
                id=ph.id,
                name=ph.name,
                description=ph.description,
                order_index=ph.order_index,
                start_date=ph.start_date,
                due_date=ph.due_date,
                completed_at=ph.completed_at,
                status=ph.status.value,
                project_id=ph.project_id,
                created_at=ph.created_at,
                updated_at=ph.updated_at,
            )
            for ph in (project.phases or [])
        ],
        task_count=task_count,
        completed_task_count=completed_count,
        hours_used=hours_used,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=PaginatedResponse[ProjectListResponse])
async def list_projects(
    client_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    project_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    base = select(Project)
    if client_id:
        base = base.where(Project.client_id == client_id)
    if status_filter:
        base = base.where(Project.status == status_filter)
    if project_type:
        base = base.where(Project.project_type == project_type)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    query = (
        base.options(*_project_load_options())
        .order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    projects = result.scalars().unique().all()

    items = []
    for p in projects:
        task_count = len(p.tasks) if p.tasks else 0
        completed_count = sum(1 for t in p.tasks if t.status == TaskStatus.completed) if p.tasks else 0
        items.append(
            ProjectListResponse(
                id=p.id,
                name=p.name,
                project_type=p.project_type,
                is_recurring=p.is_recurring,
                start_date=p.start_date,
                target_end_date=p.target_end_date,
                status=p.status.value,
                progress_percent=p.progress_percent,
                client_id=p.client_id,
                client_name=p.client.name if p.client else None,
                phase_count=len(p.phases) if p.phases else 0,
                task_count=task_count,
                completed_task_count=completed_count,
            )
        )
    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/extract-from-pdf", response_model=ProjectExtract)
async def extract_project_from_pdf(
    file: UploadFile = File(...),
    _: object = Depends(require_module("projects", write=True)),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "El archivo no puede superar 20MB")
    pdf_b64 = base64.b64encode(content).decode()
    client = get_anthropic_client()
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": EXTRACT_PROMPT},
        ]}],
    )
    try:
        data = parse_claude_json(message)
        return ProjectExtract(**data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"No se pudieron extraer los datos del PDF: {e}")


@router.post("/extract-from-text", response_model=ProjectExtract)
async def extract_project_from_text(
    file: UploadFile = File(...),
    _: object = Depends(require_module("projects", write=True)),
):
    if not file.filename:
        raise HTTPException(400, "Archivo sin nombre")
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("txt", "md"):
        raise HTTPException(400, "Solo se aceptan archivos .txt o .md")
    raw = await file.read()
    if len(raw) > 1 * 1024 * 1024:
        raise HTTPException(400, "El archivo no puede superar 1MB")
    text_content = raw.decode("utf-8", errors="replace")
    client = get_anthropic_client()
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": f"Documento:\n\n{text_content}\n\n---\n\n{EXTRACT_TEXT_PROMPT}"},
        ]}],
    )
    try:
        data = parse_claude_json(message)
        return ProjectExtract(**data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"No se pudieron extraer los datos del texto: {e}")


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    project = Project(
        name=body.name,
        description=body.description,
        project_type=body.project_type,
        is_recurring=body.is_recurring,
        start_date=body.start_date,
        target_end_date=body.target_end_date,
        budget_hours=body.budget_hours,
        budget_amount=body.budget_amount,
        pricing_model=body.pricing_model,
        unit_price=body.unit_price,
        unit_label=body.unit_label,
        scope=body.scope,
        client_id=body.client_id,
    )
    db.add(project)
    await db.commit()

    result = await db.execute(
        select(Project).options(*_project_load_options()).where(Project.id == project.id)
    )
    project = result.scalar_one()

    return _build_project_response(project)


@router.get("/templates")
async def get_project_templates(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    """Return available project templates from DB."""
    result = await db.execute(
        select(ProjectTemplateDB).order_by(ProjectTemplateDB.name)
    )
    templates = result.scalars().all()
    return {
        t.key: {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "phase_count": len(t.phases or []),
            "task_count": len(t.default_tasks or []),
            "pricing_model": t.pricing_model,
            "monthly_fee": float(t.monthly_fee) if t.monthly_fee else None,
            "is_recurring": t.is_recurring,
        }
        for t in templates
    }


@router.get("/templates/{template_id}")
async def get_template_detail(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    """Return full template detail including phases and tasks."""
    result = await db.execute(
        select(ProjectTemplateDB).where(ProjectTemplateDB.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": tpl.id,
        "key": tpl.key,
        "name": tpl.name,
        "description": tpl.description,
        "project_type": tpl.project_type,
        "is_recurring": tpl.is_recurring,
        "phases": tpl.phases or [],
        "default_tasks": tpl.default_tasks or [],
        "pricing_model": tpl.pricing_model,
        "monthly_fee": float(tpl.monthly_fee) if tpl.monthly_fee else None,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
    }


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Create a new project template."""
    import re
    key = body.get("key") or re.sub(r"[^a-z0-9_]", "_", body["name"].lower().strip())[:50]

    # Check unique key
    existing = await db.execute(select(ProjectTemplateDB).where(ProjectTemplateDB.key == key))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Template key '{key}' already exists")

    tpl = ProjectTemplateDB(
        key=key,
        name=body["name"],
        description=body.get("description"),
        project_type=body.get("project_type"),
        is_recurring=body.get("is_recurring", False),
        phases=body.get("phases", []),
        default_tasks=body.get("default_tasks", []),
        pricing_model=body.get("pricing_model"),
        monthly_fee=body.get("monthly_fee"),
        created_by=user.id,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return {"id": tpl.id, "key": tpl.key, "name": tpl.name}


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Update a project template."""
    result = await db.execute(select(ProjectTemplateDB).where(ProjectTemplateDB.id == template_id))
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    for field in ("name", "description", "project_type", "is_recurring", "phases", "default_tasks", "pricing_model", "monthly_fee"):
        if field in body:
            setattr(tpl, field, body[field])
    await db.commit()
    return {"id": tpl.id, "key": tpl.key, "name": tpl.name}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Delete a project template."""
    result = await db.execute(select(ProjectTemplateDB).where(ProjectTemplateDB.id == template_id))
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)
    await db.commit()


@router.post("/{project_id}/save-as-template")
async def save_project_as_template(
    project_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Save an existing project's structure as a new template."""
    result = await db.execute(
        select(Project).options(selectinload(Project.phases), selectinload(Project.tasks))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    import re
    name = body.get("name", f"Template: {project.name}")
    key = body.get("key") or re.sub(r"[^a-z0-9_]", "_", name.lower().strip())[:50]

    # Build phases
    phases = []
    phase_id_to_idx = {}
    for idx, phase in enumerate(sorted(project.phases, key=lambda p: p.order_index)):
        days = 7  # default
        if phase.start_date and phase.due_date:
            days = max((phase.due_date - phase.start_date).days, 1)
        phases.append({"name": phase.name, "default_days": days})
        phase_id_to_idx[phase.id] = idx

    # Build tasks
    default_tasks = []
    for task in project.tasks:
        phase_idx = phase_id_to_idx.get(task.phase_id, 0)
        default_tasks.append({
            "phase": phase_idx,
            "title": task.title,
            "minutes": task.estimated_minutes or 60,
        })

    tpl = ProjectTemplateDB(
        key=key,
        name=name,
        description=body.get("description", f"Based on project: {project.name}"),
        project_type=project.project_type,
        is_recurring=project.is_recurring,
        phases=phases,
        default_tasks=default_tasks,
        pricing_model=project.pricing_model,
        monthly_fee=project.monthly_fee,
        created_by=user.id,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return {"id": tpl.id, "key": tpl.key, "name": tpl.name}


@router.post("/from-template", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_from_template(
    client_id: int,
    template_key: str,
    start_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    """Create a project from a DB template with phases and tasks pre-populated."""
    result = await db.execute(
        select(ProjectTemplateDB).where(ProjectTemplateDB.key == template_key)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' not found")

    base_date = start_date or datetime.utcnow()
    template_phases = tpl.phases or []
    template_tasks = tpl.default_tasks or []

    total_days = sum(p.get("default_days", 7) for p in template_phases)

    project = Project(
        name=tpl.name,
        project_type=tpl.project_type or tpl.key,
        start_date=base_date,
        target_end_date=base_date + timedelta(days=total_days),
        client_id=client_id,
        status=ProjectStatus.planning,
        is_recurring=tpl.is_recurring,
        pricing_model=tpl.pricing_model,
        monthly_fee=tpl.monthly_fee,
    )
    db.add(project)
    await db.flush()

    phase_map = {}
    current_date = base_date
    for idx, phase_def in enumerate(template_phases):
        phase = ProjectPhase(
            name=phase_def["name"],
            order_index=idx,
            start_date=current_date,
            due_date=current_date + timedelta(days=phase_def.get("default_days", 7)),
            project_id=project.id,
        )
        db.add(phase)
        await db.flush()
        phase_map[idx] = phase
        current_date = phase.due_date

    for task_def in template_tasks:
        phase = phase_map.get(task_def.get("phase", 0))
        task = Task(
            title=task_def["title"],
            estimated_minutes=task_def.get("minutes", 60),
            client_id=client_id,
            project_id=project.id,
            phase_id=phase.id if phase else None,
            due_date=phase.due_date if phase else None,
        )
        db.add(task)

    await db.commit()

    result = await db.execute(
        select(Project).options(*_project_load_options()).where(Project.id == project.id)
    )
    project = result.scalar_one()

    return _build_project_response(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    result = await db.execute(
        select(Project).options(*_project_load_options()).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Compute hours used via TimeEntry → Task → Project
    h_result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0))
        .join(Task, TimeEntry.task_id == Task.id)
        .where(Task.project_id == project_id, TimeEntry.minutes.isnot(None))
    )
    hours_used = round(float(h_result.scalar() or 0) / 60, 2)

    return _build_project_response(project, hours_used=hours_used)


@router.get("/{project_id}/burndown")
async def project_burndown(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    """Return burndown data: completed tasks per day since project start."""
    # Verify project exists and get start date + total task count
    r = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = r.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all tasks for the project
    r_tasks = await db.execute(
        select(Task.id, Task.status, Task.updated_at)
        .where(Task.project_id == project_id)
    )
    all_tasks = r_tasks.all()
    total = len(all_tasks)
    if total == 0:
        return {"total_tasks": 0, "points": []}

    # Completed tasks grouped by date
    from collections import defaultdict
    completed_by_date: dict = defaultdict(int)
    for t in all_tasks:
        if t.status == TaskStatus.completed and t.updated_at:
            day = t.updated_at.date() if hasattr(t.updated_at, 'date') else t.updated_at
            if hasattr(day, 'date'):
                day = day.date()
            completed_by_date[day.isoformat()] += 1

    # Build cumulative series from project start
    from datetime import date, timedelta
    start = project.start_date.date() if project.start_date and hasattr(project.start_date, 'date') else (project.created_at.date() if hasattr(project.created_at, 'date') else date.today())
    end = date.today()

    points = []
    cumulative = 0
    current = start
    while current <= end:
        key = current.isoformat()
        cumulative += completed_by_date.get(key, 0)
        ideal_pct = min(1.0, (current - start).days / max(1, (end - start).days))
        points.append({
            "date": key,
            "completed": cumulative,
            "remaining": total - cumulative,
            "ideal": round(total * ideal_pct),
        })
        current += timedelta(days=1)
        if len(points) > 180:  # cap at 6 months
            break

    return {"total_tasks": total, "points": points}


_UPDATABLE_PROJECT_FIELDS = {
    "name", "description", "project_type", "is_recurring",
    "start_date", "target_end_date", "actual_end_date",
    "status", "progress_percent", "budget_hours", "budget_amount",
    "gsc_url", "ga4_property_id",
    "pricing_model", "monthly_fee", "unit_price", "unit_label", "scope",
}


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    result = await db.execute(
        select(Project).options(*_project_load_options()).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    old_status = project.status.value if hasattr(project.status, "value") else str(project.status)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field not in _UPDATABLE_PROJECT_FIELDS:
            continue
        if field == "status" and value:
            value = ProjectStatus(value)
        setattr(project, field, value)

    # Auto-update progress based on tasks
    if project.tasks:
        project.progress_percent = calculate_progress(project.tasks)

    await db.commit()
    await db.refresh(project)

    # Automation hook: project_status_changed
    new_status = project.status.value if hasattr(project.status, "value") else str(project.status)
    if new_status != old_status:
        try:
            from backend.api.routes.automations import execute_automations
            await execute_automations("project_status_changed", {
                "project_id": project.id,
                "project_name": project.name,
                "client_id": project.client_id,
                "old_status": old_status,
                "new_status": new_status,
            }, db)
        except Exception as e:
            import logging
            logging.warning("Automation hook failed for project %d: %s", project.id, e)

    return _build_project_response(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    result = await db.execute(
        select(Project).options(selectinload(Project.tasks)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Unlink tasks from project (don't delete them)
    for task in project.tasks:
        task.project_id = None
        task.phase_id = None

    await db.delete(project)
    await db.commit()


# --- Phase endpoints ---

@router.post("/{project_id}/phases", response_model=ProjectPhaseResponse, status_code=status.HTTP_201_CREATED)
async def create_phase(
    project_id: int,
    body: ProjectPhaseCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    phase = ProjectPhase(
        name=body.name,
        description=body.description,
        order_index=body.order_index,
        start_date=body.start_date,
        due_date=body.due_date,
        project_id=project_id,
    )
    db.add(phase)
    await db.commit()
    await db.refresh(phase)

    return ProjectPhaseResponse(
        id=phase.id,
        name=phase.name,
        description=phase.description,
        order_index=phase.order_index,
        start_date=phase.start_date,
        due_date=phase.due_date,
        completed_at=phase.completed_at,
        status=phase.status.value,
        project_id=phase.project_id,
        created_at=phase.created_at,
        updated_at=phase.updated_at,
    )


@router.put("/phases/{phase_id}", response_model=ProjectPhaseResponse)
async def update_phase(
    phase_id: int,
    body: ProjectPhaseUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    result = await db.execute(select(ProjectPhase).where(ProjectPhase.id == phase_id))
    phase = result.scalar_one_or_none()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")

    was_completed_before = phase.completed_at is not None
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            value = PhaseStatus(value)
            if value == PhaseStatus.completed and not phase.completed_at:
                phase.completed_at = datetime.utcnow()
        setattr(phase, field, value)

    await db.commit()
    await db.refresh(phase)

    # Automation hook: phase_completed
    if phase.completed_at and not was_completed_before:
        try:
            from backend.api.routes.automations import execute_automations
            await execute_automations("phase_completed", {
                "phase_id": phase.id,
                "phase_name": phase.name,
                "project_id": phase.project_id,
            }, db)
        except Exception:
            pass  # Never break phase update

    # Notify project members when phase is newly completed
    if phase.completed_at and not was_completed_before:
        try:
            from backend.services.notification_service import create_notification, PHASE_COMPLETED
            proj_result = await db.execute(select(Project).where(Project.id == phase.project_id))
            project = proj_result.scalar_one_or_none()
            if project:
                user_ids: set[int] = set()
                task_result = await db.execute(
                    select(Task).where(Task.project_id == project.id, Task.assigned_to.isnot(None))
                )
                for t in task_result.scalars().all():
                    if t.assigned_to:
                        user_ids.add(t.assigned_to)
                for uid in user_ids:
                    await create_notification(
                        db,
                        user_id=uid,
                        type=PHASE_COMPLETED,
                        title=f"Fase completada: {phase.name}",
                        message=f"La fase '{phase.name}' del proyecto '{project.name}' se ha completado",
                        link_url=f"/projects/{project.id}",
                        entity_type="project",
                        entity_id=project.id,
                    )
                if user_ids:
                    await db.commit()
        except Exception:
            pass  # Notification failure should never break phase update

    return ProjectPhaseResponse(
        id=phase.id,
        name=phase.name,
        description=phase.description,
        order_index=phase.order_index,
        start_date=phase.start_date,
        due_date=phase.due_date,
        completed_at=phase.completed_at,
        status=phase.status.value,
        project_id=phase.project_id,
        created_at=phase.created_at,
        updated_at=phase.updated_at,
    )


@router.delete("/phases/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects", write=True)),
):
    result = await db.execute(select(ProjectPhase).where(ProjectPhase.id == phase_id))
    phase = result.scalar_one_or_none()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")

    # Unlink tasks from phase
    for task in phase.tasks:
        task.phase_id = None

    await db.delete(phase)
    await db.commit()


@router.get("/{project_id}/tasks")
async def get_project_tasks(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_module("projects")),
):
    """Get all tasks for a project, grouped by phase."""
    result = await db.execute(
        select(Project).options(*_project_load_options()).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Group tasks by phase
    tasks_by_phase = {}
    unassigned = []

    for task in project.tasks:
        task_data = {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "priority": task.priority.value if task.priority else "medium",
            "start_date": task.start_date,
            "due_date": task.due_date,
            "estimated_minutes": task.estimated_minutes,
            "assigned_to": task.assigned_user.full_name if task.assigned_user else None,
        }
        if task.phase_id:
            if task.phase_id not in tasks_by_phase:
                tasks_by_phase[task.phase_id] = []
            tasks_by_phase[task.phase_id].append(task_data)
        else:
            unassigned.append(task_data)

    phases_with_tasks = []
    for phase in project.phases:
        phases_with_tasks.append({
            "phase": {
                "id": phase.id,
                "name": phase.name,
                "order_index": phase.order_index,
                "status": phase.status.value,
                "phase_type": phase.phase_type.value if phase.phase_type else "standard",
                "start_date": phase.start_date,
                "due_date": phase.due_date,
            },
            "tasks": tasks_by_phase.get(phase.id, []),
        })

    return {
        "project_id": project_id,
        "project_name": project.name,
        "phases": phases_with_tasks,
        "unassigned_tasks": unassigned,
    }
