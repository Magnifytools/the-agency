from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import ExpenseCategory, User
from backend.schemas.expense import ExpenseCategoryCreate, ExpenseCategoryResponse
from backend.api.deps import require_module

router = APIRouter(prefix="/api/finance/expense-categories", tags=["finance-expenses"])


@router.get("", response_model=list[ExpenseCategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    r = await db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name))
    return [ExpenseCategoryResponse.model_validate(c) for c in r.scalars().all()]


@router.post("", response_model=ExpenseCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    data: ExpenseCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    cat = ExpenseCategory(**data.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return ExpenseCategoryResponse.model_validate(cat)


@router.put("/{category_id}", response_model=ExpenseCategoryResponse)
async def update_category(
    category_id: int,
    data: ExpenseCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    r = await db.execute(select(ExpenseCategory).where(ExpenseCategory.id == category_id))
    cat = r.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    for key, value in data.model_dump().items():
        setattr(cat, key, value)
    await db.commit()
    await db.refresh(cat)
    return ExpenseCategoryResponse.model_validate(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_module("finance_expenses")),
):
    r = await db.execute(select(ExpenseCategory).where(ExpenseCategory.id == category_id))
    cat = r.scalars().first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    cat.is_active = False
    await db.commit()
