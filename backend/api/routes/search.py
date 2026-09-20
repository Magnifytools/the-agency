from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.modules import is_enabled
from backend.db.database import get_db
from backend.db.models import User, UserRole, Client, Project, Task, Lead
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


def _user_has_module(user: User, module: str) -> bool:
    """Check if a non-admin user has read access to a module."""
    if not is_enabled(module):
        return False
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
    can_read_clients = _user_has_module(current_user, "clients")

    # Clients — requires "clients" module
    if can_read_clients:
        client_result = await db.execute(
            select(Client.id, Client.name, Client.company, Client.status)
            .where(or_(Client.name.ilike(pattern), Client.company.ilike(pattern)))
            .order_by(Client.name, Client.id)
            .limit(5)
        )
        results["clients"] = [
            {"id": row.id, "name": row.name, "company": row.company, "status": row.status.value}
            for row in client_result.all()
        ]
    else:
        results["clients"] = []

    # Projects — requires "projects" module
    if _user_has_module(current_user, "projects"):
        client_name = (
            Client.name.label("client_name") if can_read_clients
            else literal(None).cast(String).label("client_name")
        )
        project_query = (
            select(Project.id, Project.name, Project.status, client_name)
            .where(Project.name.ilike(pattern))
            .order_by(Project.name, Project.id)
            .limit(5)
        )
        if can_read_clients:
            project_query = project_query.join(Client, Project.client_id == Client.id)
        project_result = await db.execute(project_query)
        results["projects"] = [
            {"id": row.id, "name": row.name, "client_name": row.client_name, "status": row.status.value}
            for row in project_result.all()
        ]
    else:
        results["projects"] = []

    # Tasks — requires "tasks" module
    if _user_has_module(current_user, "tasks"):
        client_name = (
            Client.name.label("client_name") if can_read_clients
            else literal(None).cast(String).label("client_name")
        )
        task_query = (
            select(Task.id, Task.title, Task.status, client_name)
            .where(Task.retired_at.is_(None), Task.title.ilike(pattern))
            .order_by(Task.title, Task.id)
            .limit(5)
        )
        if can_read_clients:
            task_query = task_query.outerjoin(Client, Task.client_id == Client.id)
        task_result = await db.execute(task_query)
        results["tasks"] = [
            {"id": row.id, "title": row.title, "client_name": row.client_name, "status": row.status.value}
            for row in task_result.all()
        ]
    else:
        results["tasks"] = []

    # Leads — requires "leads" module
    if _user_has_module(current_user, "leads"):
        lead_result = await db.execute(
            select(Lead.id, Lead.company_name, Lead.contact_name, Lead.status)
            .where(or_(Lead.company_name.ilike(pattern), Lead.contact_name.ilike(pattern)))
            .order_by(Lead.company_name, Lead.id)
            .limit(5)
        )
        results["leads"] = [
            {"id": row.id, "company_name": row.company_name, "contact_name": row.contact_name, "status": row.status.value}
            for row in lead_result.all()
        ]
    else:
        results["leads"] = []

    return results
