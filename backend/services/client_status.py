"""Estado del cliente: cómo va cada cliente, explicado señal a señal.

Sustituye a la antigua salud 0-100 (factores ponderados). Cada señal sale de
datos vivos y lleva su motivo; el estado global es la peor señal medida:

- ``act``   (Actuar):  algo pide intervenir ya.
- ``watch`` (Vigilar): algo empieza a torcerse.
- ``ok``    (Bien):    hay señales medidas y ninguna preocupa.
- ``no_data``:         no hay ninguna señal que medir para quien mira.

Cada señal sólo se calcula si quien mira puede leer su fuente; el consumo de
cuota (dinero) es sólo para admins. Las comunicaciones ya no cuentan (decisión
de David, 19 oct 2026): el módulo está oculto y sin uso.

Cambios en la web: si el cliente tiene URLs propias en la vigilancia de
cambios de The Agency (``web_watches``, módulo ``web``), mandan ellas: un cambio
crítico sin revisar es Vigilar. Si no tiene, se mira el resumen de Vigil como
hasta ahora (un resumen de más de 48 h se enseña pero no cuenta). Nunca las dos.

Disponibilidad de la web (monitor de caídas, módulo ``web``): una caída abierta
es Actuar; un bloqueo largo (no podemos comprobarla) es Vigilar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, or_, select

from backend.config import settings
from backend.db.models import (
    ACTIVE_TASK_STATUSES,
    Client,
    ClientReportPolicy,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.services.dashboard_access import has_module_read
from backend.services.digest_periods import enabled_cadences, period_cadence_sql, policy_digest_period
from backend.services.gsc_service import normalize_site_url
from backend.services.incident_report_conditions import delivery_is_confirmed
from backend.services.recurring_fee import active_monthly_fees
from backend.services.seo_traffic import traffic_by_site
from backend.services.temporal import business_today, civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period
from backend.services import ga4_service
from backend.services.vigil_service import client_block, summaries as vigil_summaries
from backend.services.web.changes_views import (
    client_blocks as web_change_blocks, status_reason as web_change_reason,
)
from backend.services.web.uptime_views import client_blocks as uptime_blocks, status_reason as uptime_reason

Status = Literal["ok", "watch", "act", "no_data"]
_RANK = {"no_data": 0, "ok": 1, "watch": 2, "act": 3}

# Ventana del tráfico: `seo_window` (28 días) de `seo_control`, vía `seo_traffic`:
# la misma que Control SEO, el semáforo de la lista y la incidencia de caída.
# Sin propiedad de Search Console no hay señal de tráfico: The Engine está
# congelado desde el 21 oct 2026 y ya no hace de respaldo.
# Días de margen para enviar un resumen tras cerrar su periodo.
DIGEST_GRACE_DAYS = 5
OVERDUE_ACT = 3
CONSUMPTION_WATCH_PCT = 90.0
CONSUMPTION_ACT_PCT = 110.0
# Tareas listas para entregar que se listan (el contador va sin límite).
READY_ITEMS = 5


@dataclass(frozen=True)
class Viewer:
    is_admin: bool
    tasks: bool
    digests: bool
    timesheet: bool
    web: bool = False

    @classmethod
    def of(cls, user: User) -> "Viewer":
        return cls(
            is_admin=user.role == UserRole.admin,
            tasks=has_module_read(user, "tasks"),
            digests=has_module_read(user, "digests"),
            timesheet=has_module_read(user, "timesheet"),
            web=has_module_read(user, "web"),
        )


@dataclass
class _Signals:
    reasons: list[tuple[str, str]] = field(default_factory=list)  # (status, motivo)
    measured: bool = False

    def add(self, status: Status, reason: str | None = None) -> None:
        self.measured = True
        if status in ("watch", "act") and reason:
            self.reasons.append((status, reason))

    def overall(self) -> Status:
        if not self.measured:
            return "no_data"
        worst = max((_RANK[s] for s, _ in self.reasons), default=_RANK["ok"])
        return next(k for k, v in _RANK.items() if v == worst)


# ── Señales por lotes ────────────────────────────────────────────────


async def _gsc_windows(db, sites: set[str]) -> dict[str, dict]:
    """Clics de los últimos 28 días con datos finales y de los 28 anteriores.

    Lo calcula `seo_traffic` (una consulta para todas las propiedades) con la
    ventana compartida `seo_window`: el semáforo de la lista, la incidencia de
    caída y Control SEO dan la misma cifra.
    """
    return {
        site: {"clicks": t.clicks, "previous": t.clicks_previous, "as_of": t.as_of,
               "trend": t.trend, "change_pct": t.clicks_change_pct}
        for site, t in (await traffic_by_site(db, sites)).items()
    }


async def _overdue_and_waiting(db, client_ids: list[int], today: date) -> dict[int, dict]:
    open_task = (
        Task.client_id.in_(client_ids),
        Task.retired_at.is_(None),
        Task.is_recurring.is_(False),
        Task.status.in_(ACTIVE_TASK_STATUSES),
    )
    rows = (await db.execute(select(
        Task.client_id,
        func.count(Task.id).filter(
            Task.due_date.isnot(None), func.date(Task.due_date) < today,
            Task.status != TaskStatus.waiting,
        ).label("overdue"),
        func.count(Task.id).filter(Task.status == TaskStatus.waiting).label("waiting"),
        func.count(Task.id).filter(
            Task.status == TaskStatus.waiting,
            Task.follow_up_date.isnot(None), Task.follow_up_date < today,
        ).label("followups_late"),
    ).where(*open_task).group_by(Task.client_id))).all()
    return {r.client_id: {"overdue": r.overdue, "waiting": r.waiting, "followups_late": r.followups_late}
            for r in rows}


async def _digests(db, client_ids: list[int]) -> tuple[dict[int, ClientReportPolicy], dict[tuple[int, str], date]]:
    """Políticas con alguna cadencia encendida y último periodo ENTREGADO por cadencia.

    Entregado = entrega externa confirmada (la regla de ``report_unsent``);
    ``DigestStatus.sent`` es una etiqueta sin evidencia y no cuenta.
    """
    policies = {p.client_id: p for p in (await db.scalars(select(ClientReportPolicy).where(
        ClientReportPolicy.client_id.in_(client_ids),
        or_(ClientReportPolicy.weekly_enabled.is_(True), ClientReportPolicy.monthly_enabled.is_(True)),
    ))).all()}
    if not policies:
        return policies, {}
    delivered = select(
        WeeklyDigest.client_id,
        period_cadence_sql(WeeklyDigest.period_start, WeeklyDigest.period_end).label("cadence"),
        WeeklyDigest.period_end,
    ).where(WeeklyDigest.client_id.in_(list(policies)), delivery_is_confirmed()).subquery()
    rows = (await db.execute(select(
        delivered.c.client_id, delivered.c.cadence, func.max(delivered.c.period_end),
    ).where(delivered.c.cadence.isnot(None)).group_by(delivered.c.client_id, delivered.c.cadence))).all()
    return policies, {(client_id, value): last for client_id, value, last in rows}


async def _month_effort(db, clients: list[Client], today: date, *, with_money: bool) -> dict[int, dict]:
    client_ids = [c.id for c in clients]
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    rate = func.coalesce(User.hourly_rate, settings.DEFAULT_HOURLY_RATE)
    rows = (await db.execute(
        select(
            Task.client_id,
            func.coalesce(func.sum(TimeEntry.minutes), 0),
            func.coalesce(func.sum(TimeEntry.minutes * rate / 60), 0),
        )
        .select_from(TimeEntry)
        .join(Task, TimeEntry.task_id == Task.id)
        .join(User, TimeEntry.user_id == User.id)
        .where(
            Task.client_id.in_(client_ids), TimeEntry.minutes.isnot(None),
            time_entry_civil_period(month_start, next_month),
        )
        .group_by(Task.client_id)
    )).all()
    effort = {cid: {"minutes": int(m), "cost": float(c)} for cid, m, c in rows}
    if with_money:
        fees = await active_monthly_fees(db, client_ids)
        for client in clients:
            fee = fees.get(client.id) or float(client.monthly_budget or 0)
            entry = effort.setdefault(client.id, {"minutes": 0, "cost": 0.0})
            entry["fee"] = fee or None
    return effort


async def _ready_to_deliver(db, client_id: int, policy: ClientReportPolicy | None, today: date) -> dict:
    """Trabajo terminado que aún no ha llegado al cliente en un resumen entregado.

    Una tarea cuenta desde que se completa (la revisión, si el proyecto la exige,
    ocurre antes: sólo su responsable la cierra). Llega al cliente con el
    resumen de un periodo que cubre su ``completed_at`` (así lo recoge el
    collector) cuando ese resumen tiene la entrega externa confirmada. Se mira
    desde el inicio del periodo que toca entregar ahora (cadencia de la
    política; mensual si no hay) o desde el día siguiente al último periodo
    entregado, lo más reciente: lo anterior sin entregar ya lo avisa la señal
    del resumen.
    """
    # Con las dos cadencias manda el mes (es lo que se entrega al cliente).
    cadence = "weekly" if policy and policy.weekly_enabled and not policy.monthly_enabled else "monthly"
    since, _ = policy_digest_period(cadence, today=today)
    delivered_end = await db.scalar(select(func.max(WeeklyDigest.period_end)).where(
        WeeklyDigest.client_id == client_id, delivery_is_confirmed(),
    ))
    if delivered_end is not None and delivered_end >= since:
        since = delivered_end + timedelta(days=1)
    start_dt, _ = civil_day_utc_bounds(since)
    done = (
        Task.client_id == client_id,
        Task.status == TaskStatus.completed,
        Task.completed_at >= start_dt,
        Task.retired_at.is_(None),
        Task.is_recurring.is_(False),
    )
    count = await db.scalar(select(func.count(Task.id)).where(*done))
    items = (await db.execute(
        select(Task.id, Task.title, Task.completed_at).where(*done)
        .order_by(Task.completed_at.desc(), Task.id.desc()).limit(READY_ITEMS)
    )).all()
    return {
        "since": since.isoformat(),
        "count": int(count or 0),
        "items": [{"id": t.id, "title": t.title,
                   "completed_on": business_today(now=t.completed_at).isoformat()} for t in items],
    }


# ── Estado ───────────────────────────────────────────────────────────


_DIGEST_WORST = {"ok": 0, "due": 1, "late": 2}
_CADENCE_NAME = {"monthly": "el informe mensual", "weekly": "el seguimiento semanal"}


def _digest_signals(
    policy: ClientReportPolicy | None, last_sent: dict[tuple[int, str], date], today: date,
) -> list[dict]:
    """Una señal por cadencia encendida (mensual primero)."""
    signals = []
    for cadence in enabled_cadences(policy):
        sent = last_sent.get((policy.client_id, cadence))
        _, period_end = policy_digest_period(cadence, today=today)
        if sent is not None and sent >= period_end:
            state = "ok"
        elif today <= period_end + timedelta(days=DIGEST_GRACE_DAYS):
            state = "due"
        else:
            state = "late"
        signals.append({
            "cadence": cadence,
            "last_sent_period_end": sent.isoformat() if sent else None,
            "expected_period_end": period_end.isoformat(),
            "state": state,
        })
    return signals


async def portfolio(
    db, clients: list[Client], viewer: Viewer, *, today: date | None = None, detail: bool = False,
) -> list[dict]:
    """Una fila por cliente con sus señales y su estado. Consultas por lotes.

    ``detail`` añade lo que sólo pinta la ficha de un cliente (``ready``: lo
    listo para entregar); la cartera no lo muestra y no lo calcula.
    """
    today = today or business_today()
    client_ids = [c.id for c in clients]
    if not client_ids:
        return []

    sites = {c.id: normalize_site_url(c.gsc_url) for c in clients}
    gsc = await _gsc_windows(db, {s for s in sites.values() if s})
    tasks = await _overdue_and_waiting(db, client_ids, today) if viewer.tasks else {}
    policies, last_sent = (await _digests(db, client_ids)) if viewer.digests else ({}, {})
    effort = (await _month_effort(db, clients, today, with_money=viewer.is_admin)
              if viewer.timesheet else {})
    vigil = await vigil_summaries(db, {c.vigil_slug for c in clients if c.vigil_slug})
    ga4_props = {c.id: ga4_service.normalize_property(c.ga4_property_id) for c in clients}
    ga4 = await ga4_service.windows(db, {p for p in ga4_props.values() if p})
    uptime = await uptime_blocks(db, client_ids) if viewer.web else {}
    # Quién tiene vigilancia de cambios propia se decide igual para todos los que
    # miran; el bloque y la señal, sólo para quien lee ``web``.
    web_changes = await web_change_blocks(db, client_ids)

    rows = []
    for client in clients:
        signals = _Signals()
        row: dict = {"client_id": client.id, "client_name": client.name}

        # 1. Tráfico SEO
        seo = None
        site = sites.get(client.id)
        if site and site in gsc:
            g = gsc[site]
            seo = {"source": "search_console", "clicks": g["clicks"], "clicks_previous": g["previous"],
                   "change_pct": g["change_pct"], "trend": g["trend"], "as_of": g["as_of"].isoformat()}
        row["seo"] = seo
        if seo and seo["trend"]:
            change = seo["change_pct"]
            if seo["trend"] == "drop_alert":
                signals.add("act", f"El tráfico de Google cae un {abs(change):.0f} % en 28 días")
            elif seo["trend"] == "down":
                signals.add("watch", f"El tráfico de Google baja un {abs(change):.0f} % en 28 días")
            else:
                signals.add("ok")

        # 2. Resúmenes: una señal por cadencia encendida. ``digest`` (la peor)
        # se mantiene para quien aún lee una sola.
        digests = _digest_signals(policies.get(client.id), last_sent, today) if viewer.digests else []
        row["digests"] = digests
        row["digest"] = max(digests, key=lambda d: _DIGEST_WORST[d["state"]]) if digests else None
        for digest in digests:
            name = _CADENCE_NAME[digest["cadence"]]
            if digest["state"] == "late":
                signals.add("act", f"{name[0].upper()}{name[1:]} está atrasado")
            elif digest["state"] == "due":
                signals.add("watch", f"Toca enviar {name}")
            else:
                signals.add("ok")

        # 3 y 4. Tareas vencidas y espera del cliente
        if viewer.tasks:
            t = tasks.get(client.id, {"overdue": 0, "waiting": 0, "followups_late": 0})
            row["tasks"] = t
            if t["overdue"] >= OVERDUE_ACT:
                signals.add("act", f"{t['overdue']} tareas vencidas")
            elif t["overdue"]:
                signals.add("watch", f"{t['overdue']} tarea{'s' if t['overdue'] > 1 else ''} vencida{'s' if t['overdue'] > 1 else ''}")
            else:
                signals.add("ok")
            if t["followups_late"]:
                signals.add("watch", f"{t['followups_late']} seguimiento{'s' if t['followups_late'] > 1 else ''} con el cliente sin hacer")
        else:
            row["tasks"] = None

        # Listo para entregar: no es un motivo de estado, sólo lo que hay que contar.
        row["ready"] = (
            await _ready_to_deliver(db, client.id, policies.get(client.id), today)
            if detail and viewer.tasks and viewer.digests else None
        )

        # 5. Horas del mes (y consumo de la cuota, sólo admin)
        if viewer.timesheet:
            e = effort.get(client.id, {"minutes": 0, "cost": 0.0})
            month = {"hours": round(e["minutes"] / 60, 1)}
            if viewer.is_admin and e.get("fee"):
                consumption = round(e["cost"] * 100 / e["fee"], 0)
                month.update({"fee": e["fee"], "consumption_pct": consumption})
                if consumption >= CONSUMPTION_ACT_PCT:
                    signals.add("act", f"El trabajo del mes ya cuesta el {consumption:.0f} % de la cuota")
                elif consumption >= CONSUMPTION_WATCH_PCT:
                    signals.add("watch", f"El trabajo del mes va por el {consumption:.0f} % de la cuota")
                else:
                    signals.add("ok")
            row["month"] = month
        else:
            row["month"] = None

        # GA4 (sólo se enseña; no es señal de estado): sesiones, conversiones e IA en 28 días.
        row["ga4"] = ga4.get(ga4_props.get(client.id) or "")

        # 6. Cambios en la web: las URLs propias mandan; si no hay, Vigil.
        own = web_changes.get(client.id)
        row["web_changes"] = own if viewer.web else None
        if row["web_changes"] and row["web_changes"]["last_checked_at"]:
            reason = web_change_reason(row["web_changes"])
            if reason:
                signals.add(*reason)
            else:
                signals.add("ok")
        summary = vigil.get(client.vigil_slug) if client.vigil_slug else None
        row["vigil"] = client_block(summary) if summary else None
        if row["vigil"] and row["vigil"]["fresh"] and own is None:
            critical = row["vigil"]["critical"]
            if critical:
                signals.add("watch", f"{critical} cambio{'s' if critical > 1 else ''} crítico{'s' if critical > 1 else ''} en la web sin revisar (Vigil)")
            else:
                signals.add("ok")

        # 7. Disponibilidad de la web: caída = Actuar, bloqueo largo = Vigilar.
        row["uptime"] = uptime.get(client.id) if viewer.web else None
        if row["uptime"] and row["uptime"]["last_checked_at"]:
            reason = uptime_reason(row["uptime"])
            if reason:
                signals.add(*reason)
            else:
                signals.add("ok")

        status = signals.overall()
        row["status"] = status
        # Primero lo que pide actuar.
        row["reasons"] = [r for s, r in signals.reasons if s == "act"] + [r for s, r in signals.reasons if s == "watch"]
        rows.append(row)

    rows.sort(key=lambda r: (-_RANK[r["status"]], r["client_name"].lower()))
    return rows
