"""Plan de trabajo del informe: el roadmap del cliente con el estado de sus tareas.

Las tareas del plan se llaman `E<n> - <nombre>`: E1 es el primer mes del
roadmap, E2 el segundo… y `<nombre>` coincide con `nombre` de la tarea del
roadmap. Se buscan entre las tareas del cliente (no sólo del proyecto: alguna
se quedó sin proyecto).

Estados (apartado 2 de la skill): completada → "hecho" con evidencia;
en curso, avanzada o en revisión → "curso"; esperando → "bloqueado" con el
motivo para el cliente; pendiente o backlog → "previsto". Una tarea que ya no
existe NO se marca "eliminado" sola: se avisa para que alguien lo decida.
Nunca se muestran horas.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from backend.db.models import Task, TaskStatus
from backend.services.local_report.periods import long_date, month_end
from backend.services.seo_control import normalize
from backend.services.temporal import as_utc_instant, business_zone

TITLE = re.compile(r"^\s*E(\d{1,2})\s*[-–—:]\s*(.+?)\s*$")
_STATE = {
    TaskStatus.completed: "hecho",
    TaskStatus.in_progress: "curso",
    TaskStatus.advanced: "curso",
    TaskStatus.in_review: "curso",
    TaskStatus.waiting: "bloqueado",
    TaskStatus.pending: "previsto",
    TaskStatus.backlog: "previsto",
}
# Días tras el fin de mes en los que el informe todavía refleja el estado de hoy
# (se genera el día 5). Pasado eso, un mes antiguo se rehace con su estado a fin de mes.
AS_OF_GRACE_DAYS = 10


@dataclass(frozen=True)
class PlanTask:
    id: int
    title: str
    status: TaskStatus
    completed_on: date | None
    waiting_for: str | None
    retired: bool


def as_of(period_end: date, today: date) -> date:
    limit = month_end(period_end)
    return today if (today - limit).days <= AS_OF_GRACE_DAYS else limit


async def load_tasks(db, client_id: int, project_id: int | None) -> list[PlanTask]:
    """Tareas del cliente (o del proyecto del plan) cuyo título sigue el patrón E<n>."""
    query = select(Task).where(Task.title.op("~")(r"^\s*E[0-9]{1,2}\s*[-–—:]"))
    if project_id:
        query = query.where((Task.client_id == client_id) | (Task.project_id == project_id))
    else:
        query = query.where(Task.client_id == client_id)
    tasks = (await db.scalars(query.order_by(Task.id))).all()
    zone = business_zone()
    return [
        PlanTask(
            id=t.id, title=t.title, status=t.status,
            completed_on=as_utc_instant(t.completed_at).astimezone(zone).date() if t.completed_at else None,
            waiting_for=t.waiting_for, retired=t.retired_at is not None,
        )
        for t in tasks if not t.is_recurring
    ]


def _key(text: str) -> str:
    return normalize(text or "")


def apply(base: dict, tasks: list[PlanTask], *, as_of_day: date,
          previous: dict | None = None) -> tuple[dict, list[str], list[dict]]:
    """(roadmap, avisos, tareas en espera sin motivo redactado)."""
    roadmap = copy.deepcopy(base)
    months = sorted(roadmap.get("meses") or {})
    prev_motivos = {
        (mon, _key(t.get("nombre"))): t.get("motivo")
        for mon, m in ((previous or {}).get("meses") or {}).items() for t in m.get("tareas", [])
        if t.get("estado") == "bloqueado" and t.get("motivo")
    }
    by_slot: dict[tuple[str, str], PlanTask] = {}
    warnings: list[str] = []
    for task in tasks:
        match = TITLE.match(task.title)
        if not match:
            continue
        index = int(match.group(1)) - 1
        if not 0 <= index < len(months):
            warnings.append(f"La tarea #{task.id} \"{task.title}\" no corresponde a ningún mes del plan.")
            continue
        slot = (months[index], _key(match.group(2)))
        if task.retired:
            continue
        by_slot.setdefault(slot, task)

    pending_motivos: list[dict] = []
    for mon in months:
        month = roadmap["meses"][mon]
        month["comentario"] = None
        for item in month.get("tareas", []):
            for key in [k for k in item if "hora" in k.lower()]:
                item.pop(key)
            item["resultado"] = None
            task = by_slot.get((mon, _key(item.get("nombre"))))
            if task is None:
                warnings.append(
                    f"No encuentro en The Agency la tarea del plan \"{item.get('nombre')}\" ({mon}): "
                    "se deja como estaba. Si se ha quitado del plan, márcala como eliminada a mano.")
                continue
            state = _STATE.get(task.status, "previsto")
            if state == "hecho" and not (task.completed_on and task.completed_on <= as_of_day):
                # Completada después de la fecha del informe: entonces seguía prevista.
                state = "previsto"
            item["estado"] = state
            item["evidencia"] = (f"The Agency #{task.id}, completada el {long_date(task.completed_on)}"
                                 if state == "hecho" else None)
            item["tarea_id"] = task.id
            if state == "bloqueado":
                motivo = prev_motivos.get((mon, _key(item.get("nombre")))) or item.get("motivo")
                item["motivo"] = motivo
                if not motivo or task.waiting_for:
                    pending_motivos.append({"mes": mon, "nombre": item.get("nombre"), "tarea_id": task.id,
                                            "esperando": task.waiting_for, "motivo_actual": motivo})
            else:
                item.pop("motivo", None)
    return roadmap, warnings, pending_motivos
