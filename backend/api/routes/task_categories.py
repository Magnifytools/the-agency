from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import TaskCategory, User
from backend.schemas.task_category import TaskCategoryCreate, TaskCategoryUpdate, TaskCategoryResponse
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/task-categories", tags=["task_categories"])


@router.get("", response_model=list[TaskCategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(TaskCategory).order_by(TaskCategory.name))
    return result.scalars().all()


@router.post("", response_model=TaskCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: TaskCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cat = TaskCategory(**body.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.put("/{category_id}", response_model=TaskCategoryResponse)
async def update_category(
    category_id: int,
    body: TaskCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(TaskCategory).where(TaskCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cat, field, value)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(TaskCategory).where(TaskCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")
    await db.delete(cat)
    await db.commit()
