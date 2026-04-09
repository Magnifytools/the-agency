"""Team resources — shared bookmarks, tools, articles."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, TeamResource
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/resources", tags=["team-resources"])

# Categoría = temática del recurso
CATEGORIES = {"ia", "seo", "diseño", "desarrollo", "marketing", "producto", "ventas", "contenido", "analítica"}

# Tipo = formato del recurso
RESOURCE_TYPES = {
    "herramienta", "guía", "prompt", "template", "extensión", "dataset",
    "inspiración", "caso de estudio", "artículo", "vídeo", "librería", "idea",
}

# Tags agrupados (el frontend los muestra por grupo)
PREDEFINED_TAGS = {
    "tecnología": ["chatgpt", "claude", "cursor", "midjourney", "wordpress", "airtable", "webflow", "zapier"],
    "uso": ["automatización", "generación de contenido", "scraping", "análisis", "diseño ui", "branding", "copywriting", "prototipado", "productividad"],
    "nivel": ["básico", "intermedio", "avanzado"],
    "formato": ["framework", "checklist", "sistema", "workflow", "librería"],
    "objetivo": ["captar leads", "mejorar ctr", "escalar contenido", "ahorrar tiempo", "aumentar conversión"],
}


class ResourceCreate(BaseModel):
    title: str
    url: Optional[str] = None
    description: Optional[str] = None
    category: str = "ia"
    resource_type: str = "herramienta"
    tags: Optional[str] = None


class ResourceUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    resource_type: Optional[str] = None
    tags: Optional[str] = None
    is_pinned: Optional[bool] = None


class ResourceResponse(BaseModel):
    id: int
    title: str
    url: Optional[str] = None
    description: Optional[str] = None
    category: str
    resource_type: str = "herramienta"
    tags: Optional[str] = None
    shared_by: int
    shared_by_name: Optional[str] = None
    is_pinned: bool = False
    created_at: str
    model_config = {"from_attributes": True}


def _to_response(r: TeamResource) -> ResourceResponse:
    return ResourceResponse(
        id=r.id,
        title=r.title,
        url=r.url,
        description=r.description,
        category=r.category,
        resource_type=r.resource_type or "herramienta",
        tags=r.tags,
        shared_by=r.shared_by,
        shared_by_name=r.user.short_name or r.user.full_name if r.user else None,
        is_pinned=r.is_pinned,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@router.get("/tags")
async def list_tags():
    """Return predefined tags grouped by category."""
    return PREDEFINED_TAGS


@router.get("/categories")
async def list_categories():
    """Return available categories and resource types."""
    return {
        "categories": sorted(CATEGORIES),
        "resource_types": sorted(RESOURCE_TYPES),
    }


@router.get("")
async def list_resources(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(TeamResource).order_by(
        TeamResource.is_pinned.desc(),
        TeamResource.created_at.desc(),
    )

    if category and category in CATEGORIES:
        query = query.where(TeamResource.category == category)

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                TeamResource.title.ilike(term),
                TeamResource.description.ilike(term),
                TeamResource.tags.ilike(term),
                TeamResource.url.ilike(term),
            )
        )

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    resources = result.scalars().all()

    # Count total
    count_query = select(func.count(TeamResource.id))
    if category and category in CATEGORIES:
        count_query = count_query.where(TeamResource.category == category)
    if search:
        term = f"%{search}%"
        count_query = count_query.where(
            or_(
                TeamResource.title.ilike(term),
                TeamResource.description.ilike(term),
                TeamResource.tags.ilike(term),
            )
        )
    total = (await db.execute(count_query)).scalar() or 0

    return {
        "items": [_to_response(r) for r in resources],
        "total": total,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_resource(
    body: ResourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Categoría inválida. Opciones: {', '.join(sorted(CATEGORIES))}")
    if body.resource_type not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Opciones: {', '.join(sorted(RESOURCE_TYPES))}")
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio")

    resource = TeamResource(
        title=body.title.strip(),
        url=body.url.strip() if body.url else None,
        description=body.description.strip() if body.description else None,
        category=body.category,
        resource_type=body.resource_type,
        tags=body.tags.strip() if body.tags else None,
        shared_by=current_user.id,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return _to_response(resource)


@router.put("/{resource_id}")
async def update_resource(
    resource_id: int,
    body: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(TeamResource).where(TeamResource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")

    update_data = body.model_dump(exclude_unset=True)
    if "category" in update_data and update_data["category"] not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoría inválida")

    for field, value in update_data.items():
        setattr(resource, field, value)

    await db.commit()
    await db.refresh(resource)
    return _to_response(resource)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(TeamResource).where(TeamResource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    await db.delete(resource)
    await db.commit()
