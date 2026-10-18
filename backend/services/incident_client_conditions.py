"""Client SEO traffic condition, read from the synced Engine summary."""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import and_, exists, false, func, literal, or_, select

from backend.config import settings
from backend.core.modules import is_enabled
from backend.db.models import Client, ClientStatus, Notification, Project, ProjectStatus, User, UserRole
from backend.services.incident_conditions import Condition, module_permission
from backend.services.seo_traffic import seo_traffic, traffic_drop_clause

CLIENT_SEO_TRAFFIC_DROP = "client_seo_traffic_drop"
CLIENT_CONDITIONS = (CLIENT_SEO_TRAFFIC_DROP,)

_OWNED_PROJECT_STATUSES = (ProjectStatus.active, ProjectStatus.planning)


def _key(client_id: int) -> str:
    # One open cycle per drop: it resolves when traffic recovers, so a dismissal
    # holds while the same drop lasts and daily syncs do not reopen it.
    return f"{CLIENT_SEO_TRAFFIC_DROP}:client:{client_id}:open"


def _recipient_clause(user_id):
    """Admins, and whoever owns an operational project of the client."""
    return or_(
        exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin),
        exists().where(
            Project.client_id == Client.id,
            Project.owner_id == user_id,
            Project.status.in_(_OWNED_PROJECT_STATUSES),
        ),
    )


def _source_clause():
    return and_(
        Client.status == ClientStatus.active,
        Client.is_internal.is_(False),
        Client.engine_project_id.is_not(None),
        traffic_drop_clause(Client.engine_summary_data),
    )


def _number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _pct(value: float) -> str:
    return f"{value:+.1f} %".replace(".", ",")


async def collect_client_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    if not is_enabled("clients"):
        return {}
    rows = (await db.execute(select(Client.id, Client.name, Client.engine_summary_data).where(
        _source_clause(), _recipient_clause(user_id), module_permission(user_id, "clients"),
    ).order_by(Client.id))).all()
    result: dict[str, Condition] = {}
    for row in rows:
        traffic = seo_traffic(row.engine_summary_data)
        if traffic is None or traffic.trend != "drop_alert":
            continue
        drop = traffic.clicks_change_pct or 0.0
        message = (
            f"Clics orgánicos en 30 días: {_number(traffic.clicks)} frente a "
            f"{_number(traffic.clicks_previous)} en los 30 anteriores ({_pct(drop)})."
        )
        if traffic.impressions_change_pct is not None:
            message += f" Impresiones: {_pct(traffic.impressions_change_pct)}."
        as_of = row.engine_summary_data.get("as_of")
        if isinstance(as_of, str):
            message += f" Datos de Engine a {as_of}."
        key = _key(row.id)
        result[key] = Condition(
            key=key,
            kind=CLIENT_SEO_TRAFFIC_DROP,
            entity_id=row.id,
            title=f"Cae el tráfico SEO: {row.name or f'Cliente #{row.id}'} ({_pct(drop)})"[:255],
            message=message,
            fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            severity="critical" if -drop >= 2 * settings.SEO_DROP_ALERT_PCT else "warning",
            entity_type="client",
            entity_key=str(row.id),
            href=f"/clients/{row.id}",
        )
    return result


def client_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled("clients"):
        return false()
    source = [Client.id == Notification.entity_id, _recipient_clause(user_id)]
    if current_only:
        source += [_source_clause(), Notification.dedupe_key == func.concat(CLIENT_SEO_TRAFFIC_DROP, ":client:", Client.id, ":open")]
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "client",
        Notification.type.in_(CLIENT_CONDITIONS),
        module_permission(user_id, "clients"),
        select(literal(1)).where(*source).exists(),
    )
