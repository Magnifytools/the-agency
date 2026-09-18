"""Bounded natural-language commands over the shared transactional writers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ACTIVE_TASK_STATUSES, Client, CommandReceipt, Task, TaskPriority,
    TaskStatus, User, UserRole,
)
from backend.services.change_journal import capture_manual_time
from backend.services.domain_writes import create_project, create_task, lock_task, update_task
from backend.services.time_writes import create_manual_time_entry

STATUS_INPUT = "needs_input"
STATUS_REVIEW = "needs_review"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def request_hash(text: str, channel: str, context: dict | None) -> str:
    return canonical_hash({"text": text.strip(), "channel": channel, "context": context})


def _permission(user: User, module: str, *, write: bool) -> bool:
    if user.role == UserRole.admin:
        return True
    return any(p.module == module and (p.can_write if write else p.can_read)
               for p in (user.permissions or []))


def require_permission(user: User, module: str, *, write: bool = True) -> None:
    if not _permission(user, module, write=write):
        raise HTTPException(403, f"Sin acceso de {'escritura' if write else 'lectura'} al módulo: {module}")


def parse_command(raw: str) -> dict[str, Any]:
    """Deterministic Spanish parser. Page context is deliberately absent."""
    text = " ".join(raw.strip().split())
    patterns = (
        (r"^(?:crea|crear) (?:un )?proyecto (.+?) (?:para|del) cliente (.+)$", "create_project"),
        (r"^(?:crea|crear) (?:una )?tarea(?: llamada)? (.+)$", "create_task"),
        (r"^(?:completa|completar|marca como completada) (?:la )?tarea (.+)$", "complete_task"),
        (r"^(?:reprograma|reprogramar) (?:la )?tarea (.+?) (?:para|al) (\d{4}-\d{2}-\d{2})$", "reschedule_task"),
        (r"^(?:pon|cambia) (?:la )?prioridad (?:de (?:la )?tarea )?(.+?) (?:a|en) (urgente|alta|media|baja)$", "set_priority"),
        (r"^(?:registra|registrar|añade|añadir) (\d+) minutos (?:en|a) (?:la )?tarea (.+)$", "log_time"),
    )
    for pattern, kind in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = [g.strip() for g in match.groups()]
        if kind == "create_project":
            return {"kind": kind, "project_name": groups[0], "client_name": groups[1]}
        if kind == "create_task":
            return {"kind": kind, "title": groups[0]}
        if kind == "complete_task":
            return {"kind": kind, "task_name": groups[0]}
        if kind == "reschedule_task":
            try:
                scheduled = date.fromisoformat(groups[1])
            except ValueError:
                return {"kind": "invalid", "error": "La fecha debe existir y usar AAAA-MM-DD"}
            return {"kind": kind, "task_name": groups[0], "scheduled_date": scheduled.isoformat()}
        if kind == "set_priority":
            priority = {"urgente": "urgent", "alta": "high", "media": "medium", "baja": "low"}[groups[1].lower()]
            return {"kind": kind, "task_name": groups[0], "priority": priority}
        if kind == "log_time":
            return {"kind": kind, "minutes": int(groups[0]), "task_name": groups[1]}
    lowered = text.casefold()
    if any(word in lowered for word in ("prioridades", "prioridad")) and lowered.startswith(("qué", "que", "muestra", "consulta")):
        return {"kind": "query_work", "query": "priorities"}
    if any(word in lowered for word in ("bloqueos", "bloqueadas", "esperando")):
        return {"kind": "query_work", "query": "blockers"}
    return {"kind": "unsupported"}


def _choice(entity: str, row, label: str, subtitle: str | None = None) -> dict:
    return {"id": f"{entity}:{row.id}", "label": label, "subtitle": subtitle}


async def _resolve_named(db: AsyncSession, model, name_column, name: str, entity: str):
    rows = list((await db.execute(select(model).where(func.lower(name_column) == name.casefold())
                                  .order_by(model.id))).scalars().all())
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, {"questions": [{"field": f"{entity}_id", "label": f"No encuentro «{name}». Elige otra entidad desde su flujo.", "kind": "notice", "choices": []}]}
    choices = []
    for row in rows:
        if entity == "task":
            choices.append(_choice(entity, row, row.title, row.project.name if row.project else "Sin proyecto"))
        else:
            choices.append(_choice(entity, row, row.name))
    return None, {"questions": [{"field": f"{entity}_id", "label": f"¿Cuál «{name}»?", "kind": "choice", "choices": choices}]}


def _entity_result(kind: str, row, *, task: Task | None = None) -> dict:
    target = task or row
    return {"type": kind, "id": row.id, "label": getattr(row, "title", getattr(row, "name", "")),
            "project_id": getattr(target, "project_id", None), "client_id": getattr(target, "client_id", None)}


async def execute_or_prompt(db: AsyncSession, receipt: CommandReceipt, actor: User) -> None:
    intent = dict(receipt.intent or {})
    kind = intent.get("kind")
    receipt.prompt = None
    receipt.error_code = receipt.error_detail = None
    if kind == "unsupported":
        receipt.status = STATUS_FAILED
        receipt.error_code = "unsupported_command"
        receipt.error_detail = "No reconozco esa orden. Usa crear/completar/reprogramar/prioridad/registrar minutos o consulta prioridades/bloqueos."
        return
    if kind == "invalid":
        receipt.status = STATUS_FAILED
        receipt.error_code = "invalid_command"
        receipt.error_detail = intent.get("error") or "La orden no es válida"
        return
    if kind == "create_project":
        require_permission(actor, "projects")
        client_id = intent.get("client_id")
        if client_id is None:
            client, prompt = await _resolve_named(db, Client, Client.name, intent["client_name"], "client")
            if prompt:
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            client_id = client.id
        project = await create_project(db, {"name": intent["project_name"], "client_id": client_id})
        entities = [_entity_result("project", project)]
        message = f"Proyecto «{project.name}» creado"
    elif kind == "create_task":
        require_permission(actor, "tasks")
        task = await create_task(db, {"title": intent["title"]}, actor=actor)
        entities = [_entity_result("task", task)]
        message = f"Tarea «{task.title}» creada"
    elif kind in {"complete_task", "reschedule_task", "set_priority", "log_time"}:
        require_permission(actor, "timesheet" if kind == "log_time" else "tasks")
        if kind == "log_time":
            require_permission(actor, "tasks", write=False)
        task_id = intent.get("task_id")
        if task_id is None:
            task, prompt = await _resolve_named(db, Task, Task.title, intent["task_name"], "task")
            if prompt:
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            task_id = task.id
        task = await lock_task(db, int(task_id))
        if kind == "complete_task":
            await update_task(db, task, {"status": TaskStatus.completed}, actor=actor)
            message = f"Tarea «{task.title}» completada"
        elif kind == "reschedule_task":
            await update_task(db, task, {"scheduled_date": date.fromisoformat(intent["scheduled_date"])}, actor=actor)
            message = f"Tarea «{task.title}» reprogramada"
        elif kind == "set_priority":
            await update_task(db, task, {"priority": TaskPriority(intent["priority"])}, actor=actor)
            message = f"Prioridad de «{task.title}» actualizada"
        else:
            capture_manual_time(db.sync_session)
            await create_manual_time_entry(db, user_id=actor.id, minutes=int(intent["minutes"]), task_id=task.id, notes="[command]")
            message = f"Registrados {intent['minutes']} minutos en «{task.title}»"
        entities = [_entity_result("task", task)]
    elif kind == "query_work":
        require_permission(actor, "tasks", write=False)
        page = await query_work(db, intent["query"], page=1, page_size=25)
        receipt.status = STATUS_EXECUTED
        receipt.result = {"message": f"{page['total']} tareas", "entities": [], "query": page,
                          "undo_available": False}
        return
    else:
        raise HTTPException(422, "Tipo de orden no permitido")
    receipt.status = STATUS_EXECUTED
    receipt.result = {"message": message, "entities": entities, "undo_available": False}


async def query_work(db: AsyncSession, kind: str, *, page: int, page_size: int) -> dict:
    query = select(Task).where(Task.status.in_(ACTIVE_TASK_STATUSES))
    if kind == "blockers":
        query = query.where(or_(Task.status == TaskStatus.waiting, Task.waiting_for.isnot(None)))
        query = query.order_by(Task.due_date.asc().nullslast(), Task.id)
    elif kind == "priorities":
        query = query.order_by(Task.priority, Task.due_date.asc().nullslast(), Task.id)
    else:
        raise HTTPException(422, "Consulta de trabajo no válida")
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = list((await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"kind": kind, "items": [_entity_result("task", task) for task in rows],
            "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}


def apply_answers(receipt: CommandReceipt, answers: list[dict]) -> None:
    intent = dict(receipt.intent or {})
    expected = {q["field"]: q for q in (receipt.prompt or {}).get("questions", [])}
    for answer in answers:
        field = answer["field"]
        question = expected.get(field)
        if question is None:
            raise HTTPException(422, f"Respuesta inesperada: {field}")
        choice_id = answer.get("choice_id")
        allowed = {choice["id"] for choice in question.get("choices", [])}
        if choice_id not in allowed:
            raise HTTPException(409, "La elección ya no es válida")
        prefix, raw_id = choice_id.split(":", 1)
        if field != f"{prefix}_id":
            raise HTTPException(422, "La elección no corresponde a la pregunta")
        intent[field] = int(raw_id)
    receipt.intent = intent


def response_dict(row: CommandReceipt) -> dict:
    return {"id": row.id, "request_key": row.request_key, "raw_text": row.raw_text,
            "channel": row.channel, "context": row.context, "status": row.status,
            "intent": row.intent, "prompt": row.prompt, "result": row.result,
            "change_log_id": row.change_log_id,
            "error": ({"code": row.error_code, "detail": row.error_detail} if row.error_code else None),
            "revision": row.revision, "created_at": row.created_at, "updated_at": row.updated_at}


def step_hash(kind: str, revision: int, payload: Any) -> str:
    return canonical_hash({"kind": kind, "revision": revision, "payload": payload})


def check_step_replay(row: CommandReceipt, key: str, payload_hash: str) -> bool:
    prior = (row.step_replays or {}).get(key)
    if prior is None:
        return False
    if prior != payload_hash:
        raise HTTPException(409, "La clave idempotente ya se usó con otro contenido")
    return True


def record_step(row: CommandReceipt, key: str, payload_hash: str) -> None:
    replays = dict(row.step_replays or {})
    if len(replays) >= 20 and key not in replays:
        raise HTTPException(409, "El recibo alcanzó el límite de pasos")
    replays[key] = payload_hash
    row.step_replays = replays
