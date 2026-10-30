"""Peticiones fuera de alcance: alta, decisión y totales del mes.

Lo usan la pestaña "Peticiones extra" de la ficha (``/api/clients/{id}/scope-requests``)
y "Petición extra" de Por aclarar (``/api/inbox/{id}/scope-request``), para que
las dos escriban igual. No hace commit.

Permisos: leer = lectura de ``clients``; escribir = escritura de ``clients``
(lo decide la ruta). Vincular un proyecto pide además leer ``projects`` y que
el proyecto sea de ese cliente; quien no lee proyectos no ve a cuál está ligada.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from backend.db.models import Client, ClientScopeRequest, Project, User
from backend.services.dashboard_access import has_module_read
from backend.services.temporal import business_today

#: decisión -> clave del total del mes.
TOTAL_KEYS = {
    "absorb": "absorbed_minutes",
    "bill": "billable_minutes",
    "swap": "swapped_minutes",
    "pending": "pending_minutes",
}


def month_range(month: str | None, *, today: date | None = None) -> tuple[date, date, str]:
    """``YYYY-MM`` -> (día 1, día 1 del mes siguiente, clave). Sin mes: el actual."""
    if month is None:
        start = (today or business_today()).replace(day=1)
    else:
        if len(month) != 7 or month[4] != "-":
            raise ValueError("El mes va como AAAA-MM")
        try:
            start = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError("El mes va como AAAA-MM") from exc
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end, start.strftime("%Y-%m")


def month_totals(rows: Iterable, start: date, end: date) -> dict[str, int]:
    """Minutos por decisión de las peticiones pedidas en el mes [start, end)."""
    totals = {key: 0 for key in TOTAL_KEYS.values()}
    count = 0
    for row in rows:
        if not start <= row.requested_on < end:
            continue
        totals[TOTAL_KEYS[row.decision]] += int(row.estimated_minutes)
        count += 1
    return {**totals, "count": count}


def apply_decision(row: ClientScopeRequest, decision: str, actor: User, *, now: datetime | None = None) -> None:
    """Cambia la decisión y apunta quién y cuándo; volver a pendiente lo borra."""
    if decision == row.decision and row.decided_at is not None:
        return
    row.decision = decision
    if decision == "pending":
        row.decided_by = None
        row.decided_at = None
    else:
        row.decided_by = actor.id
        row.decided_at = now or datetime.now(timezone.utc)


async def require_client(db, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return client


async def validate_project(db, actor: User, client_id: int, project_id: int | None) -> None:
    if project_id is None:
        return
    if not has_module_read(actor, "projects"):
        raise HTTPException(status_code=403, detail="Sin permiso para consultar proyectos")
    owner_client = await db.scalar(select(Project.client_id).where(Project.id == project_id))
    if owner_client is None:
        raise HTTPException(status_code=422, detail="El proyecto no existe")
    if owner_client != client_id:
        raise HTTPException(status_code=422, detail="El proyecto no es de este cliente")


async def create_scope_request(db, *, actor: User, client_id: int, data: dict) -> ClientScopeRequest:
    await require_client(db, client_id)
    await validate_project(db, actor, client_id, data.get("project_id"))
    row = ClientScopeRequest(
        client_id=client_id,
        project_id=data.get("project_id"),
        title=data["title"],
        detail=data.get("detail"),
        estimated_minutes=data["estimated_minutes"],
        requested_on=data.get("requested_on") or business_today(),
        decision="pending",
        decision_note=data.get("decision_note"),
        created_by=actor.id,
    )
    apply_decision(row, data.get("decision") or "pending", actor)
    db.add(row)
    await db.flush()
    return row


def _display_name(user_alias):
    return func.coalesce(user_alias.short_name, user_alias.full_name)


def _query():
    creator = aliased(User)
    decider = aliased(User)
    return select(
        ClientScopeRequest,
        Project.name.label("project_name"),
        _display_name(creator).label("created_by_name"),
        _display_name(decider).label("decided_by_name"),
    ).outerjoin(Project, Project.id == ClientScopeRequest.project_id).outerjoin(
        creator, creator.id == ClientScopeRequest.created_by,
    ).outerjoin(decider, decider.id == ClientScopeRequest.decided_by)


def to_response(row, *, can_read_projects: bool) -> dict:
    request, project_name, created_by_name, decided_by_name = row
    return {
        "id": request.id,
        "client_id": request.client_id,
        "project_id": request.project_id if can_read_projects else None,
        "project_name": project_name if can_read_projects else None,
        "title": request.title,
        "detail": request.detail,
        "estimated_minutes": request.estimated_minutes,
        "requested_on": request.requested_on,
        "decision": request.decision,
        "decision_note": request.decision_note,
        "decided_at": request.decided_at,
        "decided_by_name": decided_by_name,
        "created_at": request.created_at,
        "created_by_name": created_by_name,
    }


async def load_one(db, client_id: int, request_id: int, *, actor: User) -> dict:
    row = (await db.execute(_query().where(
        ClientScopeRequest.id == request_id, ClientScopeRequest.client_id == client_id,
    ))).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Petición no encontrada")
    return to_response(row, can_read_projects=has_module_read(actor, "projects"))


async def list_for_month(db, client_id: int, month: str | None, *, actor: User) -> dict:
    """Las del mes (por fecha de petición) y, además, las pendientes de antes.

    Lo pendiente de meses anteriores sigue pidiendo una decisión, así que se
    enseña; los totales cuentan sólo el mes elegido.
    """
    start, end, key = month_range(month)
    rows = (await db.execute(_query().where(
        ClientScopeRequest.client_id == client_id,
        or_(
            (ClientScopeRequest.requested_on >= start) & (ClientScopeRequest.requested_on < end),
            (ClientScopeRequest.decision == "pending") & (ClientScopeRequest.requested_on < start),
        ),
    ).order_by(ClientScopeRequest.requested_on.desc(), ClientScopeRequest.id.desc()))).all()
    can_read_projects = has_module_read(actor, "projects")
    return {
        "month": key,
        "totals": month_totals((r[0] for r in rows), start, end),
        "items": [to_response(r, can_read_projects=can_read_projects) for r in rows],
    }
