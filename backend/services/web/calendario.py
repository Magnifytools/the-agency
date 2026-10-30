"""¿Toca barrido hoy? (portado de Vigil)

Vigilar en fin de semana o festivo casi nunca aporta: nadie publica ese día y
el aviso se lee el lunes mezclado con el resto. Peor aún, un canal que recibe
mensajes en sábado se empieza a ignorar.

El job `web_sweep` mira cada minuto; es aquí donde se decide si hoy hay algo
que hacer para cada cliente. Los días van en `client_web_settings`
(`sweep_weekdays`, `sweep_skip_dates`, JSONB); NULL = lunes a viernes y sin
festivos (``capture_defaults``).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

# Festivos nacionales de España con fecha fija.
# Los autonómicos y locales no están: varían por comunidad y los añade cada uno
# desde la interfaz.
_FIJOS = (
    (1, 1),    # Año Nuevo
    (1, 6),    # Epifanía
    (5, 1),    # Fiesta del Trabajo
    (8, 15),   # Asunción
    (10, 12),  # Fiesta Nacional
    (11, 1),   # Todos los Santos
    (12, 6),   # Constitución
    (12, 8),   # Inmaculada
    (12, 25),  # Navidad
)


def domingo_de_pascua(anio: int) -> date:
    """Algoritmo de Meeus/Jones/Butcher para el cómputo gregoriano.

    Se calcula en vez de mantener una lista escrita a mano: una lista caduca en
    silencio y, cuando caduca, el barrido corre un Viernes Santo sin que nadie
    se dé cuenta hasta que llega el aviso.
    """
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    mes, dia = divmod(h + lam - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def festivos_nacionales(anio: int) -> list[str]:
    """Festivos nacionales de España de un año, en 'YYYY-MM-DD'.

    Incluye Viernes Santo (móvil). No incluye Jueves Santo ni el Lunes de
    Pascua: no son nacionales en toda España.
    """
    fechas = [date(anio, m, d) for m, d in _FIJOS]
    fechas.append(domingo_de_pascua(anio) - timedelta(days=2))  # Viernes Santo
    return sorted(f.isoformat() for f in fechas)


def _parse_lista(raw, por_defecto: list) -> list:
    """Lista guardada (JSONB ya decodificado o texto JSON). Rota o vacía = defecto.

    Un valor corrupto no puede desactivar la vigilancia en silencio.
    """
    if raw is None or raw == "":
        return por_defecto
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return por_defecto
    return raw if isinstance(raw, list) else por_defecto


def toca_barrido(settings: dict, hoy: date) -> tuple[bool, str]:
    """¿Corresponde barrer hoy? Devuelve (sí/no, motivo legible).

    El motivo se guarda y se enseña: si un día no llega aviso, tiene que poder
    responderse "no tocaba" sin entrar a mirar logs.
    """
    dias = _parse_lista(settings.get("sweep_weekdays"), [1, 2, 3, 4, 5])
    if hoy.isoweekday() not in dias:
        nombres = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        return False, f"hoy es {nombres[hoy.isoweekday() - 1]} y no está en los días configurados"

    saltar = set(_parse_lista(settings.get("sweep_skip_dates"), []))
    if hoy.isoformat() in saltar:
        return False, "es un día marcado como festivo"

    return True, "toca"
