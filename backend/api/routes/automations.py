"""Automation rules engine — CRUD + execution."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import (
    AutomationRule,
    AutomationLog,
    Task,
    User,
    TaskStatus,
    ProjectStatus,
)
from backend.api.deps import get_current_user, require_admin
from backend.api.utils.db_helpers import safe_refresh
from backend.core.modules import is_enabled
from backend.schemas.task import TaskCreate
from backend.services.domain_writes import (
    create_task as create_task_write,
    lock_task,
    lock_task_patch,
    update_task as update_task_write,
)
from backend.services.notification_service import create_notification
from backend.services.project_lifecycle import transition_project_status

router = APIRouter(prefix="/api/automations", tags=["automations"])

logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────

class AutomationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger: str  # AutomationTrigger value
    conditions: dict = {}
    action_type: str  # AutomationActionType value
    action_config: dict = {}
    is_active: bool = True


class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[str] = None
    conditions: Optional[dict] = None
    action_type: Optional[str] = None
    action_config: Optional[dict] = None
    is_active: Optional[bool] = None


# ── Helpers ──────────────────────────────────────────────

VALID_TRIGGERS = {
    "task_completed",
    "task_overdue",
    "phase_completed",
    "project_status_changed",
    "time_entry_created",
    "communication_logged",
}

VALID_ACTIONS = {
    "create_task",
    "change_task_status",
    "change_project_status",
    "assign_user",
    "send_notification",
    "send_discord",
    "create_insight",
}


_SENSITIVE_ACTION_FIELDS = {"webhook_url", "bot_token", "api_key", "secret", "password"}


def _sanitize_action_config(config: Optional[dict], action_type: str) -> dict:
    """Strip sensitive fields from action_config before returning to browser."""
    if not config:
        return {}
    sanitized = dict(config)
    for field in _SENSITIVE_ACTION_FIELDS:
        if field in sanitized:
            sanitized[field] = "••••••" if sanitized[field] else ""
    return sanitized


def _rule_to_dict(r: AutomationRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "trigger": r.trigger,
        "conditions": r.conditions or {},
        "action_type": r.action_type,
        "action_config": _sanitize_action_config(r.action_config, r.action_type),
        "is_active": r.is_active,
        "run_count": r.run_count,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "created_by": r.created_by,
        "creator_name": r.creator.full_name if r.creator else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _action_outcome(result: dict, success: bool = True) -> str:
    if result.get("skipped"):
        return "skipped"
    if not success or result.get("sent") is False or result.get("outcome") == "error":
        return "error"
    return "success"


def _log_to_dict(log: AutomationLog) -> dict:
    outcome = _action_outcome(log.action_result or {}, log.success)
    return {
        "id": log.id,
        "rule_id": log.rule_id,
        "rule_name": log.rule.name if log.rule else None,
        "trigger_event": log.trigger_event,
        "trigger_data": log.trigger_data,
        "action_result": log.action_result,
        "success": outcome == "success",
        "outcome": outcome,
        "error_message": log.error_message,
        "executed_at": log.executed_at.isoformat() if log.executed_at else None,
    }


# ── CRUD Endpoints ───────────────────────────────────────

@router.get("")
async def list_automations(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """List all automation rules."""
    result = await db.execute(
        select(AutomationRule).order_by(AutomationRule.is_active.desc(), AutomationRule.name)
    )
    rules = result.scalars().all()
    return [_rule_to_dict(r) for r in rules]


@router.get("/logs")
async def list_logs(
    rule_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """List automation execution logs."""
    q = select(AutomationLog).order_by(desc(AutomationLog.executed_at)).limit(min(limit, 200))
    if rule_id:
        q = q.where(AutomationLog.rule_id == rule_id)
    result = await db.execute(q)
    logs = result.scalars().all()
    return [_log_to_dict(l) for l in logs]


@router.get("/triggers")
async def list_triggers(
    _user=Depends(require_admin),
):
    """Return available triggers and action types for UI."""
    return {
        "triggers": [
            {"key": "task_completed", "label": "Tarea completada", "description": "Cuando una tarea se marca como completada"},
            {"key": "task_overdue", "label": "Tarea vencida", "description": "Cuando una tarea pasa de su fecha límite (check diario)"},
            {"key": "phase_completed", "label": "Fase completada", "description": "Cuando todas las tareas de una fase se completan"},
            {"key": "project_status_changed", "label": "Estado de proyecto cambia", "description": "Cuando un proyecto cambia de estado"},
            {"key": "time_entry_created", "label": "Registro de tiempo", "description": "Cuando se registra una entrada de tiempo"},
            {"key": "communication_logged", "label": "Comunicación registrada", "description": "Cuando se registra una comunicación con cliente"},
        ],
        "actions": [
            {"key": "create_task", "label": "Crear tarea", "description": "Crea una nueva tarea automáticamente"},
            {"key": "change_task_status", "label": "Cambiar estado de tarea", "description": "Cambia el estado de una tarea"},
            {"key": "change_project_status", "label": "Cambiar estado de proyecto", "description": "Cambia el estado de un proyecto"},
            {"key": "assign_user", "label": "Asignar usuario", "description": "Asigna un usuario a la tarea"},
            {"key": "send_notification", "label": "Enviar notificación", "description": "Envía una notificación in-app"},
            {"key": "send_discord", "label": "Enviar a Discord", "description": "Envía un mensaje al canal de Discord"},
            {"key": "create_insight", "label": "Crear insight PM", "description": "Crea un insight de gestión"},
        ],
    }


@router.get("/{rule_id}")
async def get_automation(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Get a single automation rule with recent logs."""
    result = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    # Get recent logs
    logs_result = await db.execute(
        select(AutomationLog)
        .where(AutomationLog.rule_id == rule_id)
        .order_by(desc(AutomationLog.executed_at))
        .limit(20)
    )
    logs = logs_result.scalars().all()

    data = _rule_to_dict(rule)
    data["recent_logs"] = [_log_to_dict(l) for l in logs]
    return data


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_automation(
    body: AutomationCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    """Create a new automation rule."""
    if body.trigger not in VALID_TRIGGERS:
        raise HTTPException(400, f"Trigger inválido. Válidos: {', '.join(sorted(VALID_TRIGGERS))}")
    if body.action_type not in VALID_ACTIONS:
        raise HTTPException(400, f"Acción inválida. Válidas: {', '.join(sorted(VALID_ACTIONS))}")

    rule = AutomationRule(
        name=body.name,
        description=body.description,
        trigger=body.trigger,
        conditions=body.conditions,
        action_type=body.action_type,
        action_config=body.action_config,
        is_active=body.is_active,
        created_by=user.id,
    )
    db.add(rule)
    await db.commit()
    await safe_refresh(db, rule, log_context="automations")
    return _rule_to_dict(rule)


@router.put("/{rule_id}")
async def update_automation(
    rule_id: int,
    body: AutomationUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Update an automation rule."""
    result = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    update_data = body.model_dump(exclude_unset=True)
    if "trigger" in update_data and update_data["trigger"] not in VALID_TRIGGERS:
        raise HTTPException(400, "Trigger inválido")
    if "action_type" in update_data and update_data["action_type"] not in VALID_ACTIONS:
        raise HTTPException(400, "Acción inválida")

    if update_data.get("is_active") and update_data.get("trigger", rule.trigger) not in VALID_TRIGGERS:
        raise HTTPException(400, "Este trigger no tiene ejecución disponible")

    for k, v in update_data.items():
        setattr(rule, k, v)

    await db.commit()
    await safe_refresh(db, rule, log_context="automations")
    return _rule_to_dict(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Delete an automation rule and its logs."""
    result = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    await db.delete(rule)
    await db.commit()


@router.post("/{rule_id}/toggle")
async def toggle_automation(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Toggle an automation rule on/off."""
    result = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    if not rule.is_active and rule.trigger not in VALID_TRIGGERS:
        raise HTTPException(400, "Este trigger no tiene ejecución disponible")
    rule.is_active = not rule.is_active
    await db.commit()
    await safe_refresh(db, rule, log_context="automations")
    return _rule_to_dict(rule)


# ── Engine: Execute automations ──────────────────────────

async def execute_automations(
    trigger: str,
    trigger_data: dict,
    db: AsyncSession,
):
    """
    Called from other parts of the app when events occur.
    Finds matching active rules and executes their actions.
    """
    # Hooks and jobs bypass the router, so the capability must be checked here.
    if not is_enabled("automations") or trigger not in VALID_TRIGGERS:
        return

    result = await db.execute(
        select(AutomationRule).where(
            AutomationRule.trigger == trigger,
            AutomationRule.is_active == True,  # noqa: E712
        )
    )
    rules = result.scalars().all()

    for rule in rules:
        if not _conditions_match(rule.conditions, trigger_data):
            continue

        error_msg = None
        try:
            # A broken FK/enum/action must not poison the caller's session or
            # prevent subsequent rules from recording their actual outcome.
            async with db.begin_nested():
                action_result = await _execute_action(
                    rule.action_type, rule.action_config or {}, trigger_data, db,
                    actor=rule.creator,
                )
                await db.flush()
            outcome = _action_outcome(action_result)
            if outcome == "error":
                error_msg = "La acción no se completó correctamente"
        except Exception as exc:
            outcome = "error"
            # Transport/SQL exceptions may contain webhook credentials or data.
            error_msg = f"Acción fallida ({type(exc).__name__})"
            action_result = {}
            logger.warning("Automation id=%d failed (%s)", rule.id, type(exc).__name__)
        action_result["outcome"] = outcome

        # Log execution
        log = AutomationLog(
            rule_id=rule.id,
            trigger_event=trigger,
            trigger_data=trigger_data,
            action_result=action_result,
            success=outcome == "success",
            error_message=error_msg,
            executed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(log)

        # Update rule stats
        rule.run_count = (rule.run_count or 0) + 1
        rule.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()


def _conditions_match(conditions: dict, trigger_data: dict) -> bool:
    """Check if trigger_data matches all conditions."""
    if not conditions:
        return True

    for key, expected in conditions.items():
        actual = trigger_data.get(key)
        if actual is None:
            return False
        # Support lists (any match)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False

    return True


async def _execute_action(
    action_type: str,
    action_config: dict,
    trigger_data: dict,
    db: AsyncSession,
    actor: User | None = None,
) -> dict:
    """Execute a single automation action. Returns result dict."""

    if action_type == "create_task":
        return await _action_create_task(action_config, trigger_data, db, actor=actor)
    elif action_type == "change_task_status":
        return await _action_change_task_status(action_config, trigger_data, db, actor=actor)
    elif action_type == "change_project_status":
        return await _action_change_project_status(action_config, trigger_data, db, actor=actor)
    elif action_type == "assign_user":
        return await _action_assign_user(action_config, trigger_data, db, actor=actor)
    elif action_type == "send_notification":
        return await _action_send_notification(action_config, trigger_data, db)
    elif action_type == "send_discord":
        return await _action_send_discord(action_config, trigger_data, db)
    elif action_type == "create_insight":
        return await _action_create_insight(action_config, trigger_data, db)
    else:
        return {"skipped": True, "reason": f"Unknown action: {action_type}"}


async def _action_create_task(config: dict, data: dict, db: AsyncSession, *, actor: User | None = None) -> dict:
    """Create a task from automation config."""
    task_data = TaskCreate(
        title=config.get("title", "Tarea automática"),
        description=config.get("description"),
        project_id=config.get("project_id") or data.get("project_id"),
        phase_id=config.get("phase_id") or data.get("phase_id"),
        client_id=config.get("client_id") or data.get("client_id"),
        assigned_to=config.get("assigned_to"),
        status="pending",
        priority=config.get("priority", "medium"),
        estimated_minutes=config.get("estimated_minutes"),
    ).model_dump()
    if task_data.get("assigned_to"):
        await _require_active_user(db, task_data["assigned_to"])
    task = await create_task_write(db, task_data, actor=actor)
    return {"task_id": task.id, "title": task.title}


async def _action_change_task_status(config: dict, data: dict, db: AsyncSession, *, actor: User | None = None) -> dict:
    """Change status of a task (from trigger or config)."""
    task_id = config.get("task_id") or data.get("task_id")
    new_status = TaskStatus(config.get("new_status", "pending"))
    if not task_id:
        return {"skipped": True, "reason": "No task_id"}

    try:
        task = await lock_task_patch(db, task_id, {"status": new_status})
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        task = None
    if task:
        old = task.status
        await update_task_write(db, task, {"status": new_status}, actor=actor)
        return {"task_id": task_id, "old_status": old, "new_status": new_status}
    return {"skipped": True, "reason": f"Task {task_id} not found"}


async def _action_change_project_status(config: dict, data: dict, db: AsyncSession, *, actor: User | None = None) -> dict:
    """Change project status."""
    project_id = config.get("project_id") or data.get("project_id")
    new_status = ProjectStatus(config.get("new_status", "active"))
    if not project_id:
        return {"skipped": True, "reason": "No project_id"}

    try:
        project = await transition_project_status(db, project_id, new_status, actor)
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"skipped": True, "reason": f"Project {project_id} not found"}
        raise
    old = project.__dict__.get("_lifecycle_previous_status", project.status.value)
    return {"project_id": project_id, "old_status": old, "new_status": project.status.value}


async def _require_active_user(db: AsyncSession, user_id: int) -> None:
    user = (await db.execute(select(User.id).where(User.id == user_id, User.is_active.is_(True)))).scalar_one_or_none()
    if user is None:
        raise ValueError("The target user does not exist or is inactive")


async def _action_assign_user(config: dict, data: dict, db: AsyncSession, *, actor: User | None = None) -> dict:
    """Assign user to a task."""
    task_id = config.get("task_id") or data.get("task_id")
    user_id = config.get("user_id")
    if not task_id or not user_id:
        return {"skipped": True, "reason": "Missing task_id or user_id"}

    try:
        task = await lock_task(db, task_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        task = None
    if task:
        await _require_active_user(db, user_id)
        await update_task_write(db, task, {"assigned_to": user_id}, actor=actor)
        return {"task_id": task_id, "assigned_to": user_id}
    return {"skipped": True, "reason": f"Task {task_id} not found"}


async def _action_send_notification(config: dict, data: dict, db: AsyncSession) -> dict:
    """Send an in-app notification."""
    user_id = config.get("user_id") or data.get("user_id")
    message = config.get("message", "Notificación automática")
    title = config.get("title", "Automatización")

    if not user_id:
        return {"skipped": True, "reason": "No user_id for notification"}

    await _require_active_user(db, user_id)
    notif = await create_notification(db, user_id=user_id, title=title, message=message, type="automation")
    if notif is None:
        raise RuntimeError("Notification creation failed")
    await db.flush()
    return {"notification_id": notif.id, "user_id": user_id}


async def _action_send_discord(config: dict, data: dict, db: AsyncSession) -> dict:
    """Send a Discord webhook message."""
    import httpx
    webhook_url = config.get("webhook_url")
    message = config.get("message", "Automatización ejecutada")
    if not webhook_url:
        return {"skipped": True, "reason": "No webhook_url configured"}

    # Simple template substitution
    for k, v in data.items():
        message = message.replace(f"{{{k}}}", str(v))

    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json={"content": message}, timeout=10)
        return {"status_code": resp.status_code, "sent": resp.is_success}


async def _action_create_insight(config: dict, data: dict, db: AsyncSession) -> dict:
    """Create a PM insight."""
    from backend.db.models import PMInsight
    insight = PMInsight(
        insight_type=config.get("insight_type", "suggestion"),
        priority=config.get("priority", "medium"),
        title=config.get("title", "Insight automático"),
        description=config.get("description", "Generado por automatización"),
        suggested_action=config.get("suggested_action"),
        status="active",
        client_id=config.get("client_id") or data.get("client_id"),
        project_id=config.get("project_id") or data.get("project_id"),
        task_id=config.get("task_id") or data.get("task_id"),
    )
    db.add(insight)
    await db.flush()
    return {"insight_id": insight.id}
