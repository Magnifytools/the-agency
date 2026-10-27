"""Web del cliente caída, bloqueada o con cambios críticos sin revisar.

- ``client_site_down`` (crítica): alguna URL activa del cliente tiene una caída
  ``down`` abierta (2 ciclos fallidos seguidos, ver ``services/web/uptime.py``).
- ``client_site_blocked`` (aviso): un bloqueo (401/403/429/desafío) que dura
  más de ``UPTIME_BLOCKED_ALERT_MINUTES``: no podemos comprobar la web.
- ``client_web_critical_change`` (crítica): la vigilancia de cambios
  (``services/web/sweep.py``) detectó un cambio crítico (noindex, canonical
  borrado, página en error…) que nadie ha revisado. Se resuelve sola al
  revisarlo (``POST /api/web/changes/{id}/ack``). No cuentan las URLs
  archivadas ni las silenciadas ("no me avises").
- ``client_cert_expiring`` / ``client_domain_expiring``: el certificado TLS o el
  dominio de un host vigilado caduca pronto (``services/web/health.py``): aviso
  a <=14/<=30 días, crítica a <=3/<=7 (o ya caducado). Se resuelve al renovarse.
- ``client_robots_blocked`` (crítica): el robots.txt bloquea la web entera a
  Google (``Disallow: /`` para ``*`` o Googlebot). Se resuelve al quitarlo.
- ``client_robots_changed`` (aviso): el robots.txt cambió y nadie lo ha revisado
  (``POST /api/clients/{id}/web/robots/review``).
- ``client_sitemap_broken`` (aviso): el sitemap declarado (o ``/sitemap.xml``)
  no responde, no es XML válido o no trae URLs.
  Las tres de robots/sitemap sólo con la vigilancia de cambios encendida.

Una incidencia por cliente (clave ``...:client:{id}:open``): se resuelve sola al
cerrarse la caída. La huella lleva los ids de las caídas (o de los cambios), así
que un descarte vale mientras dure ESA caída y una nueva vuelve a avisar.
Destinatarios: admins y responsables de proyectos activos/planificados del
cliente, siempre con lectura en el módulo ``web``.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, false, func, literal, or_, select

from backend.core.modules import is_enabled
from backend.db.models import (
    Client, Notification, Project, ProjectStatus, User, UserRole, WebChange, WebChangeItem, WebHostExpiry,
    WebOutage, WebRobotsState, WebUptimeTarget, WebWatch,
)
from backend.services.incident_conditions import Condition, module_permission
from backend.services.web.digest import _RULE_LABEL, _path, changes_path
from backend.services.web.health import (
    CERT_CRITICAL_DAYS, CERT_WARNING_DAYS, DOMAIN_CRITICAL_DAYS, DOMAIN_WARNING_DAYS, days_left, level,
)
from backend.services.web.changes_views import changes_enabled
from backend.services.web.sweep import monitored_clients_clause
from backend.services.web.uptime import cause_label, local_when, monitored_clause

CLIENT_SITE_DOWN = "client_site_down"
CLIENT_SITE_BLOCKED = "client_site_blocked"
CLIENT_WEB_CRITICAL_CHANGE = "client_web_critical_change"
CLIENT_CERT_EXPIRING = "client_cert_expiring"
CLIENT_DOMAIN_EXPIRING = "client_domain_expiring"
CLIENT_ROBOTS_BLOCKED = "client_robots_blocked"
CLIENT_ROBOTS_CHANGED = "client_robots_changed"
CLIENT_SITEMAP_BROKEN = "client_sitemap_broken"
OUTAGE_CONDITIONS = (CLIENT_SITE_DOWN, CLIENT_SITE_BLOCKED)
HEALTH_CONDITIONS = (
    CLIENT_CERT_EXPIRING, CLIENT_DOMAIN_EXPIRING, CLIENT_ROBOTS_BLOCKED, CLIENT_ROBOTS_CHANGED, CLIENT_SITEMAP_BROKEN,
)
WEB_CONDITIONS = (CLIENT_SITE_DOWN, CLIENT_SITE_BLOCKED, CLIENT_WEB_CRITICAL_CHANGE, *HEALTH_CONDITIONS)
_BAD_SITEMAP = ("empty", "invalid", "error")
_MAX_LINES = 3
_KIND = {CLIENT_SITE_DOWN: "down", CLIENT_SITE_BLOCKED: "blocked"}
MODULE = "web"

_OWNED_PROJECT_STATUSES = (ProjectStatus.active, ProjectStatus.planning)


def _key(condition: str, client_id: int) -> str:
    return f"{condition}:client:{client_id}:open"


def _recipient_clause(user_id):
    """Admins, y quien lleva un proyecto operativo del cliente."""
    return or_(
        exists().where(User.id == user_id, User.is_active.is_(True), User.role == UserRole.admin),
        exists().where(
            Project.client_id == Client.id,
            Project.owner_id == user_id,
            Project.status.in_(_OWNED_PROJECT_STATUSES),
        ),
    )


def _open_outage(kind: str):
    return and_(
        WebOutage.target_id == WebUptimeTarget.id,
        WebUptimeTarget.client_id == Client.id,
        WebOutage.ended_at.is_(None),
        WebOutage.kind == kind,
        monitored_clause(),
    )


def pending_critical_clause():
    """Cambio crítico sin revisar de una URL que se sigue vigilando (correlado con ``Client``)."""
    return and_(
        WebChange.client_id == Client.id,
        WebChange.acknowledged_at.is_(None),
        WebChange.max_severity == "critical",
        WebWatch.id == WebChange.watch_id,
        WebWatch.archived_at.is_(None),
        WebWatch.muted.is_(False),
        monitored_clients_clause(),
        changes_enabled(Client.id),
    )


async def _collect_critical_changes(db, user_id: int) -> dict[str, Condition]:
    # Una sola consulta (la reconciliación tiene un presupuesto fijo de lecturas):
    # la regla crítica de cada cambio va en una subconsulta correlada.
    rule = (select(func.min(WebChangeItem.rule_code))
            .where(WebChangeItem.change_id == WebChange.id, WebChangeItem.severity == "critical")
            .scalar_subquery())
    rows = (await db.execute(
        select(Client.id, Client.name, WebChange.id.label("change_id"), WebChange.detected_at, WebWatch.url,
               rule.label("rule_code"))
        .select_from(WebChange)
        .join(WebWatch, WebWatch.id == WebChange.watch_id)
        .join(Client, Client.id == WebChange.client_id)
        .where(pending_critical_clause(), _recipient_clause(user_id), module_permission(user_id, MODULE))
        .order_by(Client.id, WebChange.detected_at.desc(), WebChange.id)
    )).all()
    if not rows:
        return {}
    labels = {r.change_id: _RULE_LABEL.get(r.rule_code, r.rule_code) for r in rows if r.rule_code}
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.id, []).append(row)
    result: dict[str, Condition] = {}
    for client_id, items in grouped.items():
        name = items[0].name or f"Cliente #{client_id}"
        lines = [f"{_path(item.url)}: {labels.get(item.change_id, 'cambio crítico')} "
                 f"(el {local_when(item.detected_at)})." for item in items[:_MAX_LINES]]
        if len(items) > _MAX_LINES:
            lines.append(f"Y {len(items) - _MAX_LINES} más.")
        count = len(items)
        title = (f"Cambio crítico en la web sin revisar: {name}" if count == 1
                 else f"{count} cambios críticos en la web sin revisar: {name}")
        key = _key(CLIENT_WEB_CRITICAL_CHANGE, client_id)
        ids = ",".join(sorted(str(item.change_id) for item in items))
        result[key] = Condition(
            key=key,
            kind=CLIENT_WEB_CRITICAL_CHANGE,
            entity_id=client_id,
            title=title[:255],
            message=" ".join(lines),
            fingerprint=hashlib.sha256(f"{key}:{ids}".encode()).hexdigest(),
            severity="critical",
            entity_type="client",
            entity_key=str(client_id),
            href=changes_path(client_id),
        )
    return result


async def collect_web_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    if not is_enabled(MODULE):
        return {}
    rows = (await db.execute(
        select(Client.id, Client.name, WebOutage.id.label("outage_id"), WebOutage.kind,
               WebOutage.started_at, WebOutage.cause, WebUptimeTarget.url, WebUptimeTarget.label)
        .select_from(WebOutage)
        .join(WebUptimeTarget, WebUptimeTarget.id == WebOutage.target_id)
        .join(Client, Client.id == WebUptimeTarget.client_id)
        .where(
            WebOutage.ended_at.is_(None), monitored_clause(),
            _recipient_clause(user_id), module_permission(user_id, MODULE),
        ).order_by(Client.id, WebOutage.started_at, WebOutage.id)
    )).all()
    grouped: dict[tuple[str, int], list] = {}
    for row in rows:
        condition = CLIENT_SITE_DOWN if row.kind == "down" else CLIENT_SITE_BLOCKED
        grouped.setdefault((condition, row.id), []).append(row)
    result: dict[str, Condition] = {}
    for (condition, client_id), items in grouped.items():
        name = items[0].name or f"Cliente #{client_id}"
        lines = []
        for item in items:
            where = item.label or item.url
            if condition == CLIENT_SITE_DOWN:
                cause = cause_label(item.cause)
                lines.append(f"{where} no responde desde el {local_when(item.started_at)}" + (f" ({cause})." if cause else "."))
            else:
                lines.append(f"{where} nos bloquea desde el {local_when(item.started_at)} "
                             f"({cause_label(item.cause) or 'bloqueo'}): no sabemos si está arriba.")
        title = (f"La web no responde: {name}" if condition == CLIENT_SITE_DOWN
                 else f"No podemos comprobar la web: {name}")
        key = _key(condition, client_id)
        outage_ids = ",".join(str(item.outage_id) for item in items)
        result[key] = Condition(
            key=key,
            kind=condition,
            entity_id=client_id,
            title=title[:255],
            message=" ".join(lines),
            fingerprint=hashlib.sha256(f"{key}:{outage_ids}".encode()).hexdigest(),
            severity="critical" if condition == CLIENT_SITE_DOWN else "warning",
            entity_type="client",
            entity_key=str(client_id),
            href=f"/clients/{client_id}?tab=web",
        )
    result.update(await _collect_critical_changes(db, user_id))
    result.update(await _collect_expiry(db, user_id, now))
    result.update(await _collect_robots(db, user_id))
    return result


# ── Salud diaria: caducidades, robots.txt y sitemap ─────────────────


def _aware(now: datetime) -> datetime:
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def _cert_soon(at):
    # days_left <= N  <=>  caduca antes de at + (N + 1) días (timedelta.days redondea hacia abajo).
    return and_(WebHostExpiry.cert_status != "no_https", WebHostExpiry.cert_expires_at.is_not(None),
                WebHostExpiry.cert_expires_at < at + timedelta(days=CERT_WARNING_DAYS + 1))


def _domain_soon(at):
    return and_(WebHostExpiry.domain_expires_at.is_not(None),
                WebHostExpiry.domain_status.in_(("ok", "error")),
                WebHostExpiry.domain_expires_at < at + timedelta(days=DOMAIN_WARNING_DAYS + 1))


def _robots_pending_change():
    return and_(WebRobotsState.robots_changed_at.is_not(None), WebRobotsState.robots_reviewed_at.is_(None))


def _robots_scope():
    return and_(WebRobotsState.client_id == Client.id, monitored_clients_clause(), changes_enabled(Client.id))


def _when(days: int) -> str:
    if days < 0:
        return f"caducó hace {-days} día{'s' if days != -1 else ''}"
    if days == 0:
        return "caduca hoy"
    return f"caduca en {days} día{'s' if days != 1 else ''}"


def _condition(kind: str, client_id: int, title: str, lines: list[str], ident: str, severity: str) -> Condition:
    key = _key(kind, client_id)
    return Condition(
        key=key, kind=kind, entity_id=client_id, title=title[:255], message=" ".join(lines),
        fingerprint=hashlib.sha256(f"{key}:{ident}".encode()).hexdigest(), severity=severity,
        entity_type="client", entity_key=str(client_id), href=f"/clients/{client_id}?tab=web",
    )


async def _collect_expiry(db, user_id: int, now: datetime) -> dict[str, Condition]:
    at = _aware(now)
    rows = (await db.execute(
        select(Client.id, Client.name, WebHostExpiry.host, WebHostExpiry.cert_status, WebHostExpiry.cert_expires_at,
               WebHostExpiry.domain_name, WebHostExpiry.domain_status, WebHostExpiry.domain_expires_at)
        .select_from(WebHostExpiry)
        .join(Client, Client.id == WebHostExpiry.client_id)
        .where(monitored_clients_clause(), or_(_cert_soon(at), _domain_soon(at)),
               _recipient_clause(user_id), module_permission(user_id, MODULE))
        .order_by(Client.id, WebHostExpiry.host)
    )).all()
    found: dict[tuple[str, int], list[tuple[str, int, str]]] = {}
    names: dict[int, str] = {}
    for row in rows:
        names[row.id] = row.name or f"Cliente #{row.id}"
        cert_days = days_left(row.cert_expires_at, at) if row.cert_status != "no_https" else None
        cert_level = level(cert_days, CERT_WARNING_DAYS, CERT_CRITICAL_DAYS)
        if cert_level in ("warning", "critical"):
            found.setdefault((CLIENT_CERT_EXPIRING, row.id), []).append((row.host, cert_days, cert_level))
        domain_days = days_left(row.domain_expires_at, at) if row.domain_status in ("ok", "error") else None
        domain_level = level(domain_days, DOMAIN_WARNING_DAYS, DOMAIN_CRITICAL_DAYS)
        if domain_level in ("warning", "critical"):
            entry = (row.domain_name or row.host, domain_days, domain_level)
            items = found.setdefault((CLIENT_DOMAIN_EXPIRING, row.id), [])
            if entry[0] not in {item[0] for item in items}:
                items.append(entry)
    result: dict[str, Condition] = {}
    for (kind, client_id), items in found.items():
        severity = "critical" if any(item[2] == "critical" for item in items) else "warning"
        what = "El certificado de" if kind == CLIENT_CERT_EXPIRING else "El dominio"
        lines = [f"{what} {name} {_when(days)}." for name, days, _ in items[:_MAX_LINES]]
        if len(items) > _MAX_LINES:
            lines.append(f"Y {len(items) - _MAX_LINES} más.")
        if kind == CLIENT_CERT_EXPIRING:
            title = f"Certificado de la web a punto de caducar: {names[client_id]}"
            lines.append("Si caduca, el navegador avisará de que la web no es segura.")
        else:
            title = f"Dominio a punto de caducar: {names[client_id]}"
            lines.append("Si no se renueva, la web y el correo del dominio dejarán de funcionar.")
        # Un descarte vale para esa caducidad y ese nivel: si pasa a crítica, vuelve a avisar.
        ident = ";".join(f"{name}:{lvl}" for name, _days, lvl in items)
        result[_key(kind, client_id)] = _condition(kind, client_id, title, lines, ident, severity)
    return result


async def _collect_robots(db, user_id: int) -> dict[str, Condition]:
    rows = (await db.execute(
        select(Client.id, Client.name, WebRobotsState.origin, WebRobotsState.robots_blocks_all,
               WebRobotsState.robots_changed_at, WebRobotsState.robots_reviewed_at, WebRobotsState.sitemap_status,
               WebRobotsState.sitemap_url, WebRobotsState.sitemap_error)
        .select_from(WebRobotsState)
        .join(Client, Client.id == WebRobotsState.client_id)
        .where(_robots_scope(), or_(WebRobotsState.robots_blocks_all.is_(True), _robots_pending_change(),
                                    WebRobotsState.sitemap_status.in_(_BAD_SITEMAP)),
               _recipient_clause(user_id), module_permission(user_id, MODULE))
        .order_by(Client.id, WebRobotsState.origin)
    )).all()
    grouped: dict[tuple[str, int], list] = {}
    names: dict[int, str] = {}
    for row in rows:
        names[row.id] = row.name or f"Cliente #{row.id}"
        if row.robots_blocks_all:
            grouped.setdefault((CLIENT_ROBOTS_BLOCKED, row.id), []).append(row)
        if row.robots_changed_at is not None and row.robots_reviewed_at is None:
            grouped.setdefault((CLIENT_ROBOTS_CHANGED, row.id), []).append(row)
        if row.sitemap_status in _BAD_SITEMAP:
            grouped.setdefault((CLIENT_SITEMAP_BROKEN, row.id), []).append(row)
    result: dict[str, Condition] = {}
    for (kind, client_id), items in grouped.items():
        name = names[client_id]
        shown = items[:_MAX_LINES]
        if kind == CLIENT_ROBOTS_BLOCKED:
            title, severity = f"El robots.txt bloquea la web a Google: {name}", "critical"
            lines = [f"{item.origin}/robots.txt tiene «Disallow: /» para todos los buscadores o para Googlebot."
                     for item in shown]
            ident = ",".join(item.origin for item in items)
        elif kind == CLIENT_ROBOTS_CHANGED:
            title, severity = f"El robots.txt ha cambiado: {name}", "warning"
            lines = [f"{item.origin}/robots.txt cambió el {local_when(item.robots_changed_at)}." for item in shown]
            lines.append("Revisa el cambio en la pestaña Web.")
            ident = ",".join(f"{item.origin}@{item.robots_changed_at.isoformat()}" for item in items)
        else:
            title, severity = f"El sitemap no funciona: {name}", "warning"
            lines = [f"{item.sitemap_url or item.origin}: {_sitemap_problem(item.sitemap_status, item.sitemap_error)}."
                     for item in shown]
            ident = ",".join(f"{item.origin}:{item.sitemap_status}:{item.sitemap_url}" for item in items)
        if len(items) > _MAX_LINES:
            lines.append(f"Y {len(items) - _MAX_LINES} más.")
        result[_key(kind, client_id)] = _condition(kind, client_id, title, lines, ident, severity)
    return result


def _sitemap_problem(status: str | None, error: str | None) -> str:
    if status == "empty":
        return "responde pero no contiene ninguna URL"
    if status == "invalid":
        return "no es un XML de sitemap válido"
    return f"no responde ({error})" if error else "no responde"


def _health_current_clause():
    """Correlado con ``Client`` y ``Notification``: la condición sigue siendo cierta ahora."""
    at = func.now()

    def keyed(kind):
        return and_(Notification.type == kind,
                    Notification.dedupe_key == func.concat(kind, ":client:", Client.id, ":open"))

    expiry = select(literal(1)).select_from(WebHostExpiry).where(
        WebHostExpiry.client_id == Client.id, monitored_clients_clause())
    robots = select(literal(1)).select_from(WebRobotsState).where(_robots_scope())
    return or_(
        and_(keyed(CLIENT_CERT_EXPIRING), expiry.where(_cert_soon(at)).exists()),
        and_(keyed(CLIENT_DOMAIN_EXPIRING), expiry.where(_domain_soon(at)).exists()),
        and_(keyed(CLIENT_ROBOTS_BLOCKED), robots.where(WebRobotsState.robots_blocks_all.is_(True)).exists()),
        and_(keyed(CLIENT_ROBOTS_CHANGED), robots.where(_robots_pending_change()).exists()),
        and_(keyed(CLIENT_SITEMAP_BROKEN), robots.where(WebRobotsState.sitemap_status.in_(_BAD_SITEMAP)).exists()),
    )


def web_visibility_clause(user_id: int, *, current_only: bool = False):
    if not is_enabled(MODULE):
        return false()
    source = [Client.id == Notification.entity_id, _recipient_clause(user_id)]
    if current_only:
        source.append(or_(
            *(
                and_(
                    Notification.type == condition,
                    Notification.dedupe_key == func.concat(condition, ":client:", Client.id, ":open"),
                    select(literal(1)).select_from(WebOutage).where(_open_outage(_KIND[condition])).exists(),
                )
                for condition in OUTAGE_CONDITIONS
            ),
            and_(
                Notification.type == CLIENT_WEB_CRITICAL_CHANGE,
                Notification.dedupe_key == func.concat(CLIENT_WEB_CRITICAL_CHANGE, ":client:", Client.id, ":open"),
                select(literal(1)).select_from(WebChange).join(WebWatch, WebWatch.id == WebChange.watch_id)
                .where(pending_critical_clause()).exists(),
            ),
            _health_current_clause(),
        ))
    return and_(
        Notification.user_id == user_id,
        Notification.entity_type == "client",
        Notification.type.in_(WEB_CONDITIONS),
        module_permission(user_id, MODULE),
        select(literal(1)).where(*source).exists(),
    )
