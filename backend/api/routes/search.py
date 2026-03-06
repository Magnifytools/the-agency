from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import User, UserRole, Client, Project, Task, Lead
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


def _user_has_module(user: User, module: str) -> bool:
    """Check if a non-admin user has read access to a module."""
    if user.role == UserRole.admin:
        return True
    return any(p.module == module and p.can_read for p in user.permissions)


@router.get("")
async def global_search(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"

    results: dict = {}

    # Clients — requires "clients" module
    if _user_has_module(current_user, "clients"):
        client_result = await db.execute(
            select(Client)
            .where(or_(Client.name.ilike(pattern), Client.company.ilike(pattern)))
            .limit(5)
        )
        results["clients"] = [
            {"id": c.id, "name": c.name, "company": c.company, "status": c.status.value}
            for c in client_result.scalars().all()
        ]
    else:
        results["clients"] = []

    # Projects — requires "projects" module
    if _user_has_module(current_user, "projects"):
        project_result = await db.execute(
            select(Project).join(Client, Project.client_id == Client.id)
            .where(Project.name.ilike(pattern))
            .limit(5)
        )
        results["projects"] = [
            {"id": p.id, "name": p.name, "client_name": p.client.name if p.client else None, "status": p.status.value}
            for p in project_result.scalars().all()
        ]
    else:
        results["projects"] = []

    # Tasks — requires "tasks" module
    if _user_has_module(current_user, "tasks"):
        task_result = await db.execute(
            select(Task).join(Client, Task.client_id == Client.id)
            .where(Task.title.ilike(pattern))
            .limit(5)
        )
        results["tasks"] = [
            {"id": t.id, "title": t.title, "client_name": t.client.name if t.client else None, "status": t.status.value}
            for t in task_result.scalars().all()
        ]
    else:
        results["tasks"] = []

    # Leads — requires "leads" module
    if _user_has_module(current_user, "leads"):
        lead_result = await db.execute(
            select(Lead)
            .where(or_(Lead.company_name.ilike(pattern), Lead.contact_name.ilike(pattern)))
            .limit(5)
        )
        results["leads"] = [
            {"id": l.id, "company_name": l.company_name, "contact_name": l.contact_name, "status": l.status.value}
            for l in lead_result.scalars().all()
        ]
    else:
        results["leads"] = []

    return results
