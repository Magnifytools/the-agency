"""Fila "Operación" del dashboard: cuatro cifras, cada una de su fuente.

Nada se calcula aquí por segunda vez: cada indicador llama al servicio que ya
decide esa regla en otra pantalla, así que el número coincide con el de la
pantalla donde se actúa.

- Cuota mensual recurrente: ``recurring_fee`` (sólo admin: es dinero).
- Proyectos con cierre vencido u horas del mes pasadas: las mismas medidas que
  los avisos ``project_closing_overdue`` / ``project_monthly_hours_exceeded``.
- Clientes en "Actuar": ``client_status.portfolio`` (la vista Cartera).
- Resúmenes mensuales sin entregar: la regla del aviso ``report_unsent``.

Un indicador vale ``None`` cuando quien mira no puede leer su fuente.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import noload

from backend.db.models import Client, ClientStatus, User, UserRole
from backend.services.client_status import Viewer, portfolio
from backend.services.dashboard_access import has_module_read
from backend.services.digest_periods import format_month
from backend.services.incident_project_conditions import hours_ratio, monthly_hours_usage, project_measure_rows
from backend.services.incident_report_conditions import unsent_monthly_clients
from backend.services.recurring_fee import active_monthly_fees
from backend.services.temporal import business_today
from backend.services.time_budget import OVER_THRESHOLD

MAX_ITEMS = 3


async def _active_external_clients(db) -> list[Client]:
    # Sin noload, las relaciones selectin de Client arrastran proyectos,
    # contactos, etc. para leer cuatro columnas.
    return list((await db.execute(
        select(Client).options(noload("*")).where(
            Client.status == ClientStatus.active, Client.is_internal.is_(False),
        ).order_by(Client.name)
    )).scalars().all())


async def _recurring_fee(db, clients: list[Client]) -> dict:
    fees = await active_monthly_fees(db, [c.id for c in clients])
    return {"total": round(sum(fees.values()), 2), "clients": len(fees)}


async def _projects_at_risk(db, now: datetime, *, with_hours: bool) -> dict:
    today = business_today(now=now)
    items = []
    for row in (await db.execute(project_measure_rows(now))).all():
        reasons, weight = [], 0.0
        end_date = row.target_end_date.date() if row.target_end_date else None
        if end_date is not None and end_date < today:
            days = (today - end_date).days
            reasons.append(f"Cierre vencido hace {days} día{'s' if days != 1 else ''}")
            weight += 1000 + days
        usage = monthly_hours_usage(row) if with_hours else None
        if usage is not None and hours_ratio(*usage) >= OVER_THRESHOLD:
            if usage[1] > 0:
                pct = usage[0] * 100 / usage[1]
                reasons.append(f"Horas del mes al {pct:.0f} %")
            else:
                pct = 100.0
                reasons.append("Sin horas este mes: el exceso del anterior se comió el presupuesto")
            weight += pct
        if reasons:
            items.append((weight, {"id": row.id, "name": row.name or f"Proyecto #{row.id}", "reasons": reasons}))
    items.sort(key=lambda item: -item[0])
    return {"count": len(items), "items": [item for _, item in items[:MAX_ITEMS]]}


async def _clients_to_act(db, clients: list[Client], user: User, now: datetime) -> dict:
    rows = [r for r in await portfolio(db, clients, Viewer.of(user), today=business_today(now=now))
            if r["status"] == "act"]
    return {
        "count": len(rows),
        "items": [{"id": r["client_id"], "name": r["client_name"], "reason": r["reasons"][0] if r["reasons"] else None}
                  for r in rows[:MAX_ITEMS]],
    }


async def _digests_unsent(db, user: User, now: datetime) -> dict:
    start, end, rows = await unsent_monthly_clients(db, user.id, business_today(now=now))
    return {
        "count": len(rows),
        "month": format_month(start),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "items": [{"id": r.id, "name": r.name} for r in rows[:MAX_ITEMS]],
    }


async def operations_summary(db, user: User, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    is_admin = user.role == UserRole.admin
    # has_module_read ya devuelve False para un módulo oculto.
    can = {module: has_module_read(user, module) for module in ("clients", "projects", "timesheet", "digests")}

    clients = await _active_external_clients(db) if can["clients"] else []
    return {
        "recurring_fee": await _recurring_fee(db, clients) if is_admin and can["clients"] and can["projects"] else None,
        "projects_at_risk": await _projects_at_risk(db, now, with_hours=can["timesheet"]) if can["projects"] else None,
        "clients_to_act": await _clients_to_act(db, clients, user, now) if can["clients"] else None,
        "digests_unsent": await _digests_unsent(db, user, now) if can["digests"] else None,
    }
