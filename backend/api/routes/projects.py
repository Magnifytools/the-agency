from __future__ import annotations
from typing import Optional

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import Project, ProjectPhase, Task, TaskStatus, PhaseStatus, ProjectStatus
from backend.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectPhaseCreate,
    ProjectPhaseUpdate,
    ProjectPhaseResponse,
    PROJECT_TEMPLATES,
)
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


def calculate_progress(tasks: list) -> int:
    """Calculate project progress based on completed tasks."""
    if not tasks:
        return 0
    completed = sum(1 for t in tasks if t.status == TaskStatus.completed)
    return int((completed / len(tasks)) * 100)


@router.get("", response_model=list[ProjectListResponse])
async def list_projects(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    project_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    query = select(Project)
    if client_id:
        query = query.where(Project.client_id == client_id)
    if status:
        query = query.where(Project.status == status)
    if project_type:
        query = query.where(Project.project_type == project_type)
    query = query.order_by(Project.created_at.desc())

    result = await db.execute(query)
    projects = result.scalars().all()

    response = []
    for p in projects:
        task_count = len(p.tasks) if p.tasks else 0
        completed_count = sum(1 for t in p.tasks if t.status == TaskStatus.completed) if p.tasks else 0
        response.append(
            ProjectListResponse(
                id=p.id,
                name=p.name,
                project_type=p.project_type,
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
    return response


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    project = Project(
        name=body.name,
        description=body.description,
        project_type=body.project_type,
        start_date=body.start_date,
        target_end_date=body.target_end_date,
        budget_hours=body.budget_hours,
        budget_amount=body.budget_amount,
        client_id=body.client_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        status=project.status.value,
        progress_percent=project.progress_percent,
        budget_hours=project.budget_hours,
        budget_amount=project.budget_amount,
        client_id=project.client_id,
        client_name=project.client.name if project.client else None,
        phases=[],
        task_count=0,
        completed_task_count=0,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/templates")
async def get_project_templates(_user=Depends(get_current_user)):
    """Return available project templates."""
    return {
        key: {"name": val["name"], "phase_count": len(val["phases"]), "task_count": len(val.get("default_tasks", []))}
        for key, val in PROJECT_TEMPLATES.items()
    }


@router.post("/from-template", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_from_template(
    client_id: int,
    template_key: str,
    start_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Create a project from a template with phases and tasks pre-populated."""
    if template_key not in PROJECT_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' not found")

    template = PROJECT_TEMPLATES[template_key]
    base_date = start_date or datetime.utcnow()

    # Calculate total days
    total_days = sum(p["default_days"] for p in template["phases"])

    # Create project
    project = Project(
        name=template["name"],
        project_type=template_key,
        start_date=base_date,
        target_end_date=base_date + timedelta(days=total_days),
        client_id=client_id,
        status=ProjectStatus.planning,
    )
    db.add(project)
    await db.flush()

    # Create phases
    phase_map = {}
    current_date = base_date
    for idx, phase_def in enumerate(template["phases"]):
        phase = ProjectPhase(
            name=phase_def["name"],
            order_index=idx,
            start_date=current_date,
            due_date=current_date + timedelta(days=phase_def["default_days"]),
            project_id=project.id,
        )
        db.add(phase)
        await db.flush()
        phase_map[idx] = phase
        current_date = phase.due_date

    # Create tasks
    for task_def in template.get("default_tasks", []):
        phase = phase_map.get(task_def["phase"])
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
    await db.refresh(project)

    # Build response
    task_count = len(project.tasks) if project.tasks else 0
    completed_count = sum(1 for t in project.tasks if t.status == TaskStatus.completed) if project.tasks else 0

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        status=project.status.value,
        progress_percent=project.progress_percent,
        budget_hours=project.budget_hours,
        budget_amount=project.budget_amount,
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
            for ph in project.phases
        ],
        task_count=task_count,
        completed_task_count=completed_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    task_count = len(project.tasks) if project.tasks else 0
    completed_count = sum(1 for t in project.tasks if t.status == TaskStatus.completed) if project.tasks else 0

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        status=project.status.value,
        progress_percent=project.progress_percent,
        budget_hours=project.budget_hours,
        budget_amount=project.budget_amount,
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
            for ph in project.phases
        ],
        task_count=task_count,
        completed_task_count=completed_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            value = ProjectStatus(value)
        setattr(project, field, value)

    # Auto-update progress based on tasks
    if project.tasks:
        project.progress_percent = calculate_progress(project.tasks)

    await db.commit()
    await db.refresh(project)

    task_count = len(project.tasks) if project.tasks else 0
    completed_count = sum(1 for t in project.tasks if t.status == TaskStatus.completed) if project.tasks else 0

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        status=project.status.value,
        progress_percent=project.progress_percent,
        budget_hours=project.budget_hours,
        budget_amount=project.budget_amount,
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
            for ph in project.phases
        ],
        task_count=task_count,
        completed_task_count=completed_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
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
    _user=Depends(get_current_user),
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
    _user=Depends(get_current_user),
):
    result = await db.execute(select(ProjectPhase).where(ProjectPhase.id == phase_id))
    phase = result.scalar_one_or_none()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            value = PhaseStatus(value)
            if value == PhaseStatus.completed and not phase.completed_at:
                phase.completed_at = datetime.utcnow()
        setattr(phase, field, value)

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


@router.delete("/phases/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_phase(
    phase_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
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
    _user=Depends(get_current_user),
):
    """Get all tasks for a project, grouped by phase."""
    result = await db.execute(select(Project).where(Project.id == project_id))
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
