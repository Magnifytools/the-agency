"""Google Analytics del informe ("Tráfico de la web"), en vivo con `ga4_live.query`.

- Adquisición de tráfico: sesiones por `sessionDefaultChannelGroup` del
  periodo, del anterior y del año anterior, más sesiones con interacción y
  eventos clave del periodo.
- Adquisición de usuarios: usuarios nuevos por `firstUserDefaultChannelGroup`
  con las mismas comparaciones, más usuarios totales.

Sin propiedad o sin acceso, `{"disponible": false}` y la plantilla pinta las
tablas en blanco con el aviso de pendiente.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.services.local_report.periods import ReportPeriods, Window

Run = Callable[..., Awaitable[dict[str, Any]]]

# Nombres de los canales como los enseña GA4 en español.
CHANNELS = {
    "Organic Search": "Búsqueda orgánica",
    "Direct": "Directo",
    "Referral": "Referencia",
    "Organic Social": "Social orgánico",
    "Paid Search": "Búsqueda de pago",
    "Paid Social": "Social de pago",
    "Organic Maps": "Mapas orgánicos",
    "Organic Video": "Vídeo orgánico",
    "Organic Shopping": "Shopping orgánico",
    "Paid Shopping": "Shopping de pago",
    "Paid Video": "Vídeo de pago",
    "Paid Other": "Otros de pago",
    "Display": "Display",
    "Cross-network": "Varias redes",
    "Email": "Correo electrónico",
    "Affiliates": "Afiliados",
    "Audio": "Audio",
    "SMS": "SMS",
    "Mobile Push Notifications": "Notificaciones push",
    "Unassigned": "Sin asignar",
    "(other)": "Sin asignar",
    "(not set)": "Sin asignar",
}


def channel_name(value: str | None) -> str:
    return CHANNELS.get(value or "", value or "Sin asignar")


async def _by_channel(run: Run, window: Window, dimension: str, metrics: list[str]) -> dict[str, dict]:
    result = await run(start_date=window.start, end_date=window.end, dimensions=[dimension],
                       metrics=metrics, limit=200)
    out: dict[str, dict] = {}
    for row in result["rows"]:
        name = channel_name(row["keys"][dimension])
        acc = out.setdefault(name, {m: 0 for m in metrics})
        for m in metrics:
            acc[m] += row["metrics"].get(m) or 0
    return out


def _round(value) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 1)


async def build(run: Run, periods: ReportPeriods) -> dict[str, Any]:
    cur, prev, yoy = periods.current, periods.previous, periods.year_ago
    dim = "sessionDefaultChannelGroup"
    t_now = await _by_channel(run, cur, dim, ["sessions", "engagedSessions", "keyEvents"])
    t_prev = await _by_channel(run, prev, dim, ["sessions"])
    t_yoy = await _by_channel(run, yoy, dim, ["sessions"])
    trafico = [
        {
            "canal": name,
            "sesiones": _round(t_now.get(name, {}).get("sessions", 0)),
            "sesiones_mes_anterior": _round(t_prev.get(name, {}).get("sessions", 0)),
            "sesiones_ano_anterior": _round(t_yoy.get(name, {}).get("sessions", 0)),
            "sesiones_interaccion": _round(t_now.get(name, {}).get("engagedSessions", 0)),
            "eventos_clave": _round(t_now.get(name, {}).get("keyEvents", 0)),
        }
        for name in _order(t_now, t_prev, t_yoy, "sessions")
    ]

    dim = "firstUserDefaultChannelGroup"
    u_now = await _by_channel(run, cur, dim, ["newUsers", "totalUsers"])
    u_prev = await _by_channel(run, prev, dim, ["newUsers"])
    u_yoy = await _by_channel(run, yoy, dim, ["newUsers"])
    usuarios = [
        {
            "canal": name,
            "usuarios_nuevos": _round(u_now.get(name, {}).get("newUsers", 0)),
            "usuarios_nuevos_mes_anterior": _round(u_prev.get(name, {}).get("newUsers", 0)),
            "usuarios_nuevos_ano_anterior": _round(u_yoy.get(name, {}).get("newUsers", 0)),
            "usuarios_totales": _round(u_now.get(name, {}).get("totalUsers", 0)),
        }
        for name in _order(u_now, u_prev, u_yoy, "newUsers")
    ]
    return {"disponible": True, "trafico": trafico, "usuarios": usuarios}


def _order(now: dict, prev: dict, yoy: dict, metric: str) -> list[str]:
    names = set(now) | set(prev) | set(yoy)
    return sorted(names, key=lambda n: (-(now.get(n, {}).get(metric) or 0),
                                        -(prev.get(n, {}).get(metric) or 0), n))
