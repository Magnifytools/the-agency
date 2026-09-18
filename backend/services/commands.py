"""Bounded natural-language commands over the shared transactional writers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ACTIVE_TASK_STATUSES, Client, ClientStatus, CommandReceipt, Project,
    ProjectStatus, Task, TaskPriority, TaskStatus, User, UserRole,
)
from backend.services.change_journal import capture_manual_time
from backend.services.domain_writes import create_project, create_task, lock_task, update_task
from backend.services.time_writes import create_manual_time_entry
from backend.services.temporal import business_today

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


_WEEKDAYS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
             "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}
_REF = r'(?:"([^"]+)"|(.+?))'


def _civil_date(label: str) -> tuple[str | None, list[str] | None, str | None]:
    """Resolve a business date once; alternatives represent real ambiguity."""
    raw = label.strip().casefold()
    today = business_today()
    if raw == "hoy":
        return today.isoformat(), None, None
    if raw == "mañana":
        return (today + timedelta(days=1)).isoformat(), None, None
    explicit_next = raw.startswith("próximo ") or raw.startswith("proximo ")
    explicit_this = raw.startswith("este ")
    weekday_name = re.sub(r"^(?:próximo|proximo|este)\s+", "", raw)
    if weekday_name in _WEEKDAYS:
        delta = (_WEEKDAYS[weekday_name] - today.weekday()) % 7
        if delta == 0 and not (explicit_next or explicit_this):
            return None, [today.isoformat(), (today + timedelta(days=7)).isoformat()], None
        if explicit_next and delta == 0:
            delta = 7
        return (today + timedelta(days=delta)).isoformat(), None, None
    try:
        return date.fromisoformat(raw).isoformat(), None, None
    except ValueError:
        return None, None, "La fecha debe ser hoy, mañana, un día de la semana o AAAA-MM-DD"


def _quoted_head(value: str) -> tuple[str | None, str]:
    value = value.strip()
    if not value.startswith('"'):
        return None, value
    match = re.match(r'^"([^"]+)"(?:\s+(.*))?$', value)
    return (match.group(1), (match.group(2) or "")) if match else (None, value)


def _peel_clause(text: str, marker: str) -> tuple[str, str | None]:
    matches = list(re.finditer(rf"(?:^|\s+){marker}\s+", text, flags=re.IGNORECASE))
    if not matches:
        return text, None
    match = matches[-1]
    value = text[match.end():].strip()
    if not value:
        return text, None
    return text[:match.start()].strip(), value.strip('"')


def _date_intent(kind: str, task_name: str, label: str, **extra) -> dict[str, Any]:
    resolved, choices, error = _civil_date(label)
    if error:
        return {"kind": "invalid", "error": error}
    intent = {"kind": kind, "task_name": task_name, "date_label": label, **extra}
    if resolved:
        intent["scheduled_date" if kind == "reschedule_task" else "entry_date"] = resolved
    else:
        intent["date_options"] = choices
    return intent


def parse_command(raw: str) -> dict[str, Any]:
    """Parse a small Spanish allowlist. Page context is deliberately absent."""
    text = " ".join(raw.strip().split())
    project_match = re.match(r"^(?:crea|crear) (?:un )?proyecto (.+)$", text, re.I)
    if project_match:
        remainder = project_match.group(1).strip()
        quoted, clauses = _quoted_head(remainder)
        if quoted is not None:
            name = quoted
        else:
            clauses = remainder
            name = None
        clauses, target_label = _peel_clause(clauses, r"fecha objetivo")
        clauses, owner = _peel_clause(clauses, r"responsable")
        clauses, client = _peel_clause(clauses, r"(?:para|del) cliente")
        if name is None:
            name, clauses = clauses.strip(), ""
        if clauses or not name or not client:
            return {"kind": "ambiguous_create", "entity": "project", "literal": remainder,
                    "error": "Usa comillas para el nombre e indica para cliente"}
        intent: dict[str, Any] = {"kind": "create_project", "project_name": name, "client_name": client}
        if owner:
            intent["owner_name"] = owner
        if target_label:
            target, options, error = _civil_date(target_label)
            if error or options:
                return {"kind": "invalid", "error": error or "Aclara la fecha objetivo con una fecha absoluta"}
            intent["target_date"] = target
        if quoted is None and re.search(r"\b(?:con|para|en)\b", name, re.I):
            return {"kind": "ambiguous_create", "entity": "project", "literal": name,
                    "candidate": intent,
                    "error": "Confirma el nombre completo o escríbelo entre comillas"}
        return intent

    task_match = re.match(r"^(?:crea|crear) (?:una )?tarea(?: llamada)? (.+)$", text, re.I)
    if task_match:
        remainder = task_match.group(1).strip()
        quoted, clauses = _quoted_head(remainder)
        title = quoted
        no_date = bool(re.search(r"\s+sin fecha$", clauses, re.I))
        if no_date:
            clauses = re.sub(r"\s+sin fecha$", "", clauses, flags=re.I).strip()
        clauses, date_label = _peel_clause(clauses, r"(?:para|el)")
        # Only treat the generic para/el suffix as a date when it really is one.
        if date_label:
            resolved, options, error = _civil_date(date_label)
            if error:
                clauses = f"{clauses} para {date_label}".strip()
                date_label = None
        else:
            resolved = options = None
        clauses, assigned = _peel_clause(clauses, r"asignad[ao] a")
        clauses, client = _peel_clause(clauses, r"para cliente")
        clauses, project = _peel_clause(clauses, r"en proyecto")
        if title is None:
            title, clauses = clauses.strip(), ""
        if clauses or not title:
            return {"kind": "ambiguous_create", "entity": "task", "literal": remainder,
                    "error": "Pon el título entre comillas para separar sus calificadores"}
        intent = {"kind": "create_task", "title": title, "schedule_mode": "none" if no_date else "omitted"}
        if project:
            intent["project_name"] = project
        if client:
            intent["client_name"] = client
        if assigned:
            intent["assigned_name"] = assigned
        if date_label:
            intent["date_label"] = date_label
            if resolved:
                intent["scheduled_date"] = resolved
            else:
                intent["date_options"] = options
        if quoted is None and re.search(r"\b(?:con|para|en)\b", title, re.I):
            return {"kind": "ambiguous_create", "entity": "task", "literal": title,
                    "candidate": intent,
                    "error": "Confirma el título completo o escríbelo entre comillas"}
        return intent

    match = re.match(r"^(?:completa|completar|marca como completada) (?:la )?tarea (.+)$", text, re.I)
    if match:
        return {"kind": "complete_task", "task_name": match.group(1).strip('" ')}
    match = re.match(r"^(?:reprograma|reprogramar) (?:la )?tarea (.+?)\s+sin fecha$", text, re.I)
    if match:
        return {"kind": "reschedule_task", "task_name": match.group(1).strip('" '), "scheduled_date": None}
    match = re.match(r"^(?:reprograma|reprogramar) (?:la )?tarea (.+?)\s+(?:para|al)\s+(.+)$", text, re.I)
    if match:
        return _date_intent("reschedule_task", match.group(1).strip('" '), match.group(2))
    match = re.match(r"^(?:pon|cambia) (?:la )?prioridad (?:de (?:la )?tarea )?(.+?) (?:a|en) (urgente|alta|media|baja)$", text, re.I)
    if match:
        priority = {"urgente": "urgent", "alta": "high", "media": "medium", "baja": "low"}[match.group(2).lower()]
        return {"kind": "set_priority", "task_name": match.group(1).strip('" '), "priority": priority}
    match = re.match(r"^(?:registra|registrar|añade|añadir) (\d+) minutos (?:en|a) (?:la )?tarea (.+)$", text, re.I)
    if match:
        task_name = match.group(2).strip()
        quoted, suffix = _quoted_head(task_name)
        if quoted is not None:
            task_name = quoted
            suffix, date_label = _peel_clause(f" {suffix}" if suffix else "", r"(?:el|para)")
            if suffix:
                return {"kind": "invalid", "error": "No se admite registrar tiempo para otra persona"}
        else:
            task_name, date_label = _peel_clause(task_name, r"(?:el|para)")
        if date_label:
            resolved, choices, error = _civil_date(date_label)
            if error:
                return {"kind": "invalid", "error": "No se admite actor o fecha no reconocidos; usa comillas en la tarea"}
            intent = {"kind": "log_time", "minutes": int(match.group(1)), "task_name": task_name, "date_label": date_label}
            intent["entry_date"] = resolved
            if choices:
                intent["date_options"] = choices
            return intent
        return {"kind": "log_time", "minutes": int(match.group(1)), "task_name": task_name}
    lowered = text.casefold()
    scope = "team" if "equipo" in lowered else "mine"
    if any(word in lowered for word in ("prioridades", "prioridad")) and lowered.startswith(("qué", "que", "muestra", "consulta")):
        return {"kind": "query_work", "query": "priorities", "scope": scope}
    if any(word in lowered for word in ("bloqueos", "bloqueadas", "esperando")):
        return {"kind": "query_work", "query": "blockers", "scope": scope}
    return {"kind": "unsupported"}


def _choice(entity: str, row, label: str, subtitle: str | None = None) -> dict:
    return {"id": f"{entity}:{row.id}", "label": label, "subtitle": subtitle}


async def _resolve_named(db: AsyncSession, model, name_column, name: str, entity: str):
    columns = name_column if isinstance(name_column, tuple) else (name_column,)
    query = select(model).where(or_(*[func.lower(column) == name.casefold() for column in columns]))
    if entity == "task":
        query = query.where(Task.is_recurring.is_(False))
    elif entity == "client":
        query = query.where(Client.status == ClientStatus.active)
    elif entity == "project":
        query = query.where(Project.status.in_([ProjectStatus.planning, ProjectStatus.active]))
    elif entity == "user":
        query = query.where(User.is_active.is_(True))
    rows = list((await db.execute(query.order_by(model.id))).scalars().all())
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, {"questions": [{"field": f"{entity}_id", "label": f"No encuentro «{name}». Elige otra entidad desde su flujo.", "kind": "notice", "choices": []}]}
    choices = []
    for row in rows:
        if entity == "task":
            choices.append(_choice(entity, row, row.title, row.project.name if row.project else "Sin proyecto"))
        elif entity == "user":
            choices.append(_choice(entity, row, row.full_name, row.short_name))
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
    if kind == "ambiguous_create":
        receipt.status = STATUS_INPUT
        receipt.prompt = {"questions": [{
            "field": "literal_title", "label": intent["error"], "kind": "choice",
            "choices": [{"id": "literal_title:confirm", "label": "Usar todo como título", "subtitle": intent["literal"]}],
        }]}
        return
    date_field = "entry_date" if kind == "log_time" else "scheduled_date"
    if intent.get("date_options") and date_field not in intent:
        receipt.status = STATUS_INPUT
        receipt.prompt = {"questions": [{
            "field": date_field, "label": f"¿Qué fecha significa «{intent.get('date_label')}»?", "kind": "choice",
            "choices": [{"id": f"date:{value}", "label": value} for value in intent["date_options"]],
        }]}
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
        owner_id = intent.get("owner_id")
        if intent.get("owner_name") and owner_id is None:
            owner, prompt = await _resolve_named(
                db, User, (User.full_name, User.short_name), intent["owner_name"], "user",
            )
            if prompt:
                prompt["questions"][0]["field"] = "owner_id"
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            owner_id = owner.id
        payload = {"name": intent["project_name"], "client_id": client_id, "owner_id": owner_id}
        if intent.get("target_date"):
            payload["target_end_date"] = datetime.combine(date.fromisoformat(intent["target_date"]), time.min)
        project = await create_project(db, payload)
        entities = [_entity_result("project", project)]
        message = f"Proyecto «{project.name}» creado"
        applied = {"client_id": client_id, "owner_id": owner_id, "target_date": intent.get("target_date")}
    elif kind == "create_task":
        require_permission(actor, "tasks")
        project_id = intent.get("project_id")
        if intent.get("project_name") and project_id is None:
            project, prompt = await _resolve_named(db, Project, Project.name, intent["project_name"], "project")
            if prompt:
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            project_id = project.id
        client_id = intent.get("client_id")
        if intent.get("client_name") and client_id is None:
            client, prompt = await _resolve_named(db, Client, Client.name, intent["client_name"], "client")
            if prompt:
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            client_id = client.id
        assigned_to = intent.get("assigned_to")
        if intent.get("assigned_name") and assigned_to is None:
            user, prompt = await _resolve_named(
                db, User, (User.full_name, User.short_name), intent["assigned_name"], "user",
            )
            if prompt:
                prompt["questions"][0]["field"] = "assigned_to"
                receipt.status, receipt.prompt = STATUS_INPUT, prompt
                return
            assigned_to = user.id
        payload = {"title": intent["title"], "project_id": project_id,
                   "client_id": client_id, "assigned_to": assigned_to}
        if intent.get("schedule_mode") == "none" or "scheduled_date" in intent:
            payload["scheduled_date"] = (date.fromisoformat(intent["scheduled_date"])
                                         if intent.get("scheduled_date") else None)
        task = await create_task(db, payload, actor=actor)
        entities = [_entity_result("task", task)]
        message = f"Tarea «{task.title}» creada"
        applied = {"project_id": task.project_id, "client_id": task.client_id,
                   "assigned_to": task.assigned_to,
                   "scheduled_date": task.scheduled_date.isoformat() if task.scheduled_date else None}
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
            scheduled = date.fromisoformat(intent["scheduled_date"]) if intent.get("scheduled_date") else None
            await update_task(db, task, {"scheduled_date": scheduled}, actor=actor)
            message = f"Tarea «{task.title}» reprogramada"
        elif kind == "set_priority":
            await update_task(db, task, {"priority": TaskPriority(intent["priority"])}, actor=actor)
            message = f"Prioridad de «{task.title}» actualizada"
        else:
            capture_manual_time(db.sync_session)
            entry_date = (datetime.combine(date.fromisoformat(intent["entry_date"]), time.min)
                          if intent.get("entry_date") else None)
            await create_manual_time_entry(db, user_id=actor.id, minutes=int(intent["minutes"]),
                                           task_id=task.id, notes="[command]", entry_date=entry_date)
            message = f"Registrados {intent['minutes']} minutos en «{task.title}»"
        entities = [_entity_result("task", task)]
        applied = {"status": task.status.value, "priority": task.priority.value,
                   "scheduled_date": task.scheduled_date.isoformat() if task.scheduled_date else None}
        if kind == "log_time":
            applied.update({"minutes": int(intent["minutes"]), "user_id": actor.id,
                            "entry_date": intent.get("entry_date") or business_today().isoformat()})
    elif kind == "query_work":
        require_permission(actor, "tasks", write=False)
        page = await query_work(db, intent["query"], actor=actor,
                                scope=intent.get("scope", "mine"), page=1, page_size=25)
        receipt.status = STATUS_EXECUTED
        receipt.result = {"message": f"{page['total']} tareas", "entities": [], "query": page,
                          "undo_available": False}
        return
    else:
        raise HTTPException(422, "Tipo de orden no permitido")
    receipt.status = STATUS_EXECUTED
    receipt.result = {"message": message, "entities": entities, "applied": applied,
                      "undo_available": False}


async def query_work(db: AsyncSession, kind: str, *, actor: User, scope: str,
                     page: int, page_size: int) -> dict:
    if scope not in {"mine", "team"}:
        raise HTTPException(422, "Ámbito de consulta no válido")
    if scope == "team" and actor.role != UserRole.admin:
        raise HTTPException(403, "Solo un administrador puede consultar el trabajo del equipo")
    query = select(Task).where(
        Task.status.in_(ACTIVE_TASK_STATUSES),
        Task.is_recurring.is_(False),
    )
    if scope == "mine":
        query = query.where(Task.assigned_to == actor.id)
    if kind == "blockers":
        query = query.where(or_(Task.status == TaskStatus.waiting, Task.waiting_for.isnot(None)))
        query = query.order_by(Task.due_date.asc().nullslast(), Task.id)
    elif kind == "priorities":
        priority_order = case(
            (Task.priority == TaskPriority.urgent, 0),
            (Task.priority == TaskPriority.high, 1),
            (Task.priority == TaskPriority.medium, 2),
            (Task.priority == TaskPriority.low, 3),
            else_=4,
        )
        query = query.order_by(priority_order, Task.due_date.asc().nullslast(), Task.id)
    else:
        raise HTTPException(422, "Consulta de trabajo no válida")
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = list((await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all())
    return {"kind": kind, "scope": scope,
            "items": [_entity_result("task", task) for task in rows],
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
        if prefix == "date" and field in {"scheduled_date", "entry_date"}:
            intent[field] = date.fromisoformat(raw_id).isoformat()
            intent.pop("date_options", None)
        elif prefix == "literal_title" and field == "literal_title":
            candidate = intent.get("candidate")
            if not candidate:
                raise HTTPException(422, "Usa comillas para separar el título y sus calificadores")
            intent = dict(candidate)
        else:
            valid_entity_field = field == f"{prefix}_id" or (prefix == "user" and field in {"owner_id", "assigned_to"})
            if not valid_entity_field:
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
