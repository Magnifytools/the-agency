from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import desc
from typing import List, Optional

from backend.db.database import get_db
from backend.db.models import GrowthIdea, User
from backend.schemas.growth import GrowthIdeaCreate, GrowthIdeaUpdate, GrowthIdeaResponse
from backend.api.deps import get_current_user, require_module

router = APIRouter(tags=["growth"])


@router.get("/api/growth", response_model=List[GrowthIdeaResponse])
async def list_growth_ideas(
    status: Optional[str] = None,
    funnel_stage: Optional[str] = None,
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

    # Order by ICE score descending
    query = query.order_by(desc(GrowthIdea.ice_score))
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
    idea_dict["ice_score"] = idea_in.impact * idea_in.confidence * idea_in.ease
    
    new_idea = GrowthIdea(**idea_dict)
    db.add(new_idea)
    await db.commit()
    await db.refresh(new_idea)
    return GrowthIdeaResponse.model_validate(new_idea)


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
            setattr(idea, field, value)
            
        # Recalculate ICE score if any of the components changed
        if "impact" in update_data or "confidence" in update_data or "ease" in update_data:
            idea.ice_score = idea.impact * idea.confidence * idea.ease

        await db.commit()
        await db.refresh(idea)
        
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
