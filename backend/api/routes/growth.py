from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import desc
from typing import List, Optional

from backend.db.database import get_db
from backend.db.models import GrowthIdea, User, Project, Task
from backend.schemas.growth import GrowthIdeaCreate, GrowthIdeaUpdate, GrowthIdeaResponse
from backend.api.deps import get_current_user, require_module
from backend.api.utils.db_helpers import safe_refresh

router = APIRouter(tags=["growth"])


@router.get("/api/growth", response_model=List[GrowthIdeaResponse])
async def list_growth_ideas(
    status: Optional[str] = None,
    funnel_stage: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth")),
):
    query = select(GrowthIdea).options(
        selectinload(GrowthIdea.project), selectinload(GrowthIdea.task)
    )

    if status:
        query = query.where(GrowthIdea.status == status)
    if funnel_stage:
        query = query.where(GrowthIdea.funnel_stage == funnel_stage)
    if project_id is not None:
        query = query.where(GrowthIdea.project_id == project_id)

    # Order by ICE score descending
    query = query.order_by(desc(GrowthIdea.ice_score)).limit(limit).offset(offset)
    result = await db.execute(query)
    ideas = result.scalars().all()

    # Build response manually to include optional nested fields flatly if wanted
    # Pydantic's from_attributes handles direct mapping, we just map relations
    response = []
    for idea in ideas:
        idea_dict = GrowthIdeaResponse.model_validate(idea).model_dump()
        idea_dict["project_name"] = idea.project.name if idea.project else None
        idea_dict["task_title"] = idea.task.title if idea.task else None
        response.append(GrowthIdeaResponse(**idea_dict))

    return response


@router.post(
    "/api/growth",
    response_model=GrowthIdeaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_growth_idea(
    idea_in: GrowthIdeaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    idea_dict = idea_in.model_dump()
    # Calculate initial ICE score
    idea_dict["ice_score"] = round((idea_in.impact + idea_in.confidence + idea_in.ease) / 3)
    
    new_idea = GrowthIdea(**idea_dict)
    db.add(new_idea)
    await db.commit()
    await safe_refresh(db, new_idea, log_context="growth")
    return GrowthIdeaResponse.model_validate(new_idea)


_UPDATABLE_GROWTH_IDEA_FIELDS = {
    "title", "description", "funnel_stage", "target_kpi", "status",
    "impact", "confidence", "ease",
    "experiment_start_date", "experiment_end_date",
    "results_notes", "is_successful", "project_id", "task_id",
}


@router.put("/api/growth/{idea_id}", response_model=GrowthIdeaResponse)
async def update_growth_idea(
    idea_id: int,
    idea_in: GrowthIdeaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(GrowthIdea).where(GrowthIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea no encontrada")

    update_data = idea_in.model_dump(exclude_unset=True)

    if update_data:
        for field, value in update_data.items():
            if field not in _UPDATABLE_GROWTH_IDEA_FIELDS:
                continue
            setattr(idea, field, value)
            
        # Recalculate ICE score if any of the components changed
        if "impact" in update_data or "confidence" in update_data or "ease" in update_data:
            idea.ice_score = round((idea.impact + idea.confidence + idea.ease) / 3)

        await db.commit()
        await safe_refresh(db, idea, log_context="growth")
        
    return GrowthIdeaResponse.model_validate(idea)


@router.delete("/api/growth/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_growth_idea(
    idea_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    result = await db.execute(select(GrowthIdea).where(GrowthIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea no encontrada")

    await db.delete(idea)
    await db.commit()


@router.post("/api/growth/{idea_id}/convert-to-project")
async def convert_to_project(
    idea_id: int,
    client_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    """Convert a growth idea into a project and link them."""
    result = await db.execute(select(GrowthIdea).where(GrowthIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea no encontrada")

    desc_parts = [idea.description] if idea.description else []
    desc_parts.append(f"Origen: Growth Idea (ICE: {idea.ice_score})")
    if idea.results_notes:
        desc_parts.append(f"Resultados: {idea.results_notes}")

    project = Project(
        name=f"[Growth] {idea.title}",
        description="\n\n".join(desc_parts),
        client_id=client_id,
        status="planning",
    )
    db.add(project)
    await db.commit()
    await safe_refresh(db, project, log_context="growth")

    idea.project_id = project.id
    idea.status = "completed"
    await db.commit()

    return {"project_id": project.id, "message": "Proyecto creado y vinculado"}


@router.post("/api/growth/{idea_id}/create-task")
async def create_task_from_idea(
    idea_id: int,
    client_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("growth", write=True)),
):
    """Create a task from a growth idea and link them."""
    result = await db.execute(select(GrowthIdea).where(GrowthIdea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea no encontrada")

    desc_parts = [idea.description] if idea.description else []
    desc_parts.append(f"Origen: Growth Idea (ICE: {idea.ice_score})")
    if idea.results_notes:
        desc_parts.append(f"Resultados: {idea.results_notes}")

    task = Task(
        title=f"[Growth] {idea.title}",
        description="\n\n".join(desc_parts),
        client_id=client_id,
        status="pending",
        priority="medium",
        created_by=current_user.id,
    )
    db.add(task)
    await db.commit()
    await safe_refresh(db, task, log_context="growth")

    idea.task_id = task.id
    idea.status = "completed"
    await db.commit()

    return {"task_id": task.id, "message": "Tarea creada y vinculada"}
