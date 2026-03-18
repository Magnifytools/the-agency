from __future__ import annotations

"""
Lightweight audit logging for critical operations.

Uses a dedicated logger so audit events can be routed to a separate
log file or external service without touching application logs.

Usage:
    from backend.api.middleware.audit_log import log_audit
    log_audit(user_id=current_user.id, action="create", resource_type="task", resource_id=task.id)
"""
import logging
from datetime import datetime, timezone

audit_logger = logging.getLogger("audit")


def log_audit(
    user_id: int | str,
    action: str,
    resource_type: str,
    resource_id: int | str | None = None,
    details: str = "",
) -> None:
    """Record an audit event as a structured log line.

    Args:
        user_id: ID of the user performing the action.
        action: Verb describing the operation (create, delete, send, etc.).
        resource_type: Type of resource being acted upon (task, project, etc.).
        resource_id: Optional ID of the specific resource.
        details: Optional free-text detail (truncated to 200 chars).
    """
    audit_logger.info(
        "AUDIT user=%s action=%s resource=%s/%s ts=%s detail=%s",
        user_id,
        action,
        resource_type,
        resource_id or "-",
        datetime.now(timezone.utc).isoformat(),
        details[:200],
    )
