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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select

from backend.config import settings
from backend.db.models import (
    ACTIVE_TASK_STATUSES,
    Client,
    ClientReportPolicy,
    DigestStatus,
    GscDaily,
    GscSiteSync,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.services.dashboard_access import has_module_read
from backend.services.digest_periods import policy_digest_period
from backend.services.gsc_service import normalize_site_url
from backend.services.seo_traffic import STABLE_BAND_PCT, is_traffic_drop, seo_traffic
from backend.services.temporal import business_today
from backend.services.time_entry_dates import time_entry_civil_period

Status = Literal["ok", "watch", "act", "no_data"]
_RANK = {"no_data": 0, "ok": 1, "watch": 2, "act": 3}

# Ventana del tráfico: 28 días (4 semanas completas, sin sesgo de día de la semana).
SEO_WINDOW_DAYS = 28
# Días de margen para enviar un resumen tras cerrar su periodo.
DIGEST_GRACE_DAYS = 5
OVERDUE_ACT = 3
CONSUMPTION_WATCH_PCT = 90.0
CONSUMPTION_ACT_PCT = 110.0


@dataclass(frozen=True)
class Viewer:
    is_admin: bool
    tasks: bool
    digests: bool
    timesheet: bool

    @classmethod
    def of(cls, user: User) -> "Viewer":
        return cls(
            is_admin=user.role == UserRole.admin,
            tasks=has_module_read(user, "tasks"),
            digests=has_module_read(user, "digests"),
            timesheet=has_module_read(user, "timesheet"),
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


def _pct(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) * 100 / previous, 1)


def _trend(clicks: int, previous: int) -> tuple[str | None, float | None]:
    change = _pct(clicks, previous)
    if is_traffic_drop(clicks, previous):
        return "drop_alert", change
    if change is None:
        return None, None
    if change > STABLE_BAND_PCT:
        return "up", change
    if change < -STABLE_BAND_PCT:
        return "down", change
    return "stable", change


# ── Señales por lotes ────────────────────────────────────────────────


async def _gsc_windows(db, sites: set[str]) -> dict[str, dict]:
    """Clics de los últimos 28 días con datos finales y de los 28 anteriores."""
    if not sites:
        return {}
    states = (await db.scalars(select(GscSiteSync).where(
        GscSiteSync.site_url.in_(sites), GscSiteSync.backfilled_at.isnot(None),
        GscSiteSync.last_data_date.isnot(None),
    ))).all()
    out = {}
    for state in states:
        end = state.last_data_date
        start = end - timedelta(days=SEO_WINDOW_DAYS - 1)
        prev_start = start - timedelta(days=SEO_WINDOW_DAYS)
        row = (await db.execute(select(
            func.coalesce(func.sum(GscDaily.clicks).filter(GscDaily.date >= start), 0),
            func.coalesce(func.sum(GscDaily.clicks).filter(GscDaily.date < start), 0),
        ).where(
            GscDaily.site_url == state.site_url,
            GscDaily.date >= prev_start, GscDaily.date <= end,
        ))).one()
        out[state.site_url] = {"clicks": int(row[0]), "previous": int(row[1]), "as_of": end}
    return out


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


async def _digests(db, client_ids: list[int]) -> tuple[dict[int, ClientReportPolicy], dict[int, date]]:
    policies = {p.client_id: p for p in (await db.scalars(select(ClientReportPolicy).where(
        ClientReportPolicy.client_id.in_(client_ids), ClientReportPolicy.enabled.is_(True),
    ))).all()}
    last_sent = dict((await db.execute(select(
        WeeklyDigest.client_id, func.max(WeeklyDigest.period_end),
    ).where(
        WeeklyDigest.client_id.in_(client_ids), WeeklyDigest.status == DigestStatus.sent,
    ).group_by(WeeklyDigest.client_id))).all())
    return policies, last_sent


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
        fees = dict((await db.execute(select(
            Project.client_id, func.coalesce(func.sum(Project.monthly_fee), 0),
        ).where(
            Project.client_id.in_(client_ids), Project.status == ProjectStatus.active,
        ).group_by(Project.client_id))).all())
        for client in clients:
            fee = float(fees.get(client.id) or 0) or float(client.monthly_budget or 0)
            entry = effort.setdefault(client.id, {"minutes": 0, "cost": 0.0})
            entry["fee"] = fee or None
    return effort


# ── Estado ───────────────────────────────────────────────────────────


def _digest_signal(policy: ClientReportPolicy | None, last_sent: date | None, today: date) -> dict | None:
    if policy is None:
        return None
    period_start, period_end = policy_digest_period(policy.cadence.value, today=today)
    if last_sent is not None and last_sent >= period_end:
        state = "ok"
    elif today <= period_end + timedelta(days=DIGEST_GRACE_DAYS):
        state = "due"
    else:
        state = "late"
    return {
        "cadence": policy.cadence.value,
        "last_sent_period_end": last_sent.isoformat() if last_sent else None,
        "expected_period_end": period_end.isoformat(),
        "state": state,
    }


async def portfolio(db, clients: list[Client], viewer: Viewer, *, today: date | None = None) -> list[dict]:
    """Una fila por cliente con sus señales y su estado. Consultas por lotes."""
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

    rows = []
    for client in clients:
        signals = _Signals()
        row: dict = {"client_id": client.id, "client_name": client.name}

        # 1. Tráfico SEO
        seo = None
        site = sites.get(client.id)
        if site and site in gsc:
            g = gsc[site]
            trend, change = _trend(g["clicks"], g["previous"])
            seo = {"source": "search_console", "clicks": g["clicks"], "clicks_previous": g["previous"],
                   "change_pct": change, "trend": trend, "as_of": g["as_of"].isoformat()}
        else:
            engine = seo_traffic(client.engine_summary_data) if client.engine_project_id else None
            if engine is not None:
                seo = {"source": "engine", "clicks": engine.clicks, "clicks_previous": engine.clicks_previous,
                       "change_pct": engine.clicks_change_pct, "trend": engine.trend,
                       "as_of": (client.engine_summary_data or {}).get("as_of")}
        row["seo"] = seo
        if seo and seo["trend"]:
            change = seo["change_pct"]
            if seo["trend"] == "drop_alert":
                signals.add("act", f"El tráfico de Google cae un {abs(change):.0f} % en 28 días")
            elif seo["trend"] == "down":
                signals.add("watch", f"El tráfico de Google baja un {abs(change):.0f} % en 28 días")
            else:
                signals.add("ok")

        # 2. Resumen
        digest = _digest_signal(policies.get(client.id), last_sent.get(client.id), today) if viewer.digests else None
        row["digest"] = digest
        if digest:
            label = "mensual" if digest["cadence"] == "monthly" else "semanal"
            if digest["state"] == "late":
                signals.add("act", f"El resumen {label} está atrasado")
            elif digest["state"] == "due":
                signals.add("watch", f"Toca enviar el resumen {label}")
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

        status = signals.overall()
        row["status"] = status
        # Primero lo que pide actuar.
        row["reasons"] = [r for s, r in signals.reasons if s == "act"] + [r for s, r in signals.reasons if s == "watch"]
        rows.append(row)

    rows.sort(key=lambda r: (-_RANK[r["status"]], r["client_name"].lower()))
    return rows
