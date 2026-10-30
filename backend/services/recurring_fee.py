"""Cuota mensual recurrente: la suma de ``Project.monthly_fee`` de los proyectos activos.

Fuente única de lo que factura cada cliente al mes (ver "Pricing Architecture"
en CLAUDE.md). La lee el estado del cliente (consumo de la cuota) y la fila
"Operación" del dashboard; ``Client.monthly_budget`` es legado y no entra aquí.
"""
from __future__ import annotations

from sqlalchemy import func, select

from backend.db.models import Project, ProjectStatus


async def active_monthly_fees(db, client_ids: list[int]) -> dict[int, float]:
    """Cuota mensual por cliente; sólo clientes con algún proyecto activo con cuota."""
    if not client_ids:
        return {}
    rows = (await db.execute(select(
        Project.client_id, func.coalesce(func.sum(Project.monthly_fee), 0),
    ).where(
        Project.client_id.in_(client_ids),
        Project.status == ProjectStatus.active,
        Project.monthly_fee > 0,
    ).group_by(Project.client_id))).all()
    return {client_id: float(fee) for client_id, fee in rows}
