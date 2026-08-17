"""Módulos ocultos: un único interruptor para toda la aplicación.

Contexto (auditoría ago 2026): 279 de los 349 endpoints no recibieron una sola
llamada en 77 días. En vez de borrar ~16.000 líneas de golpe, se ocultan: el
router no se registra y la interfaz no ofrece la pantalla, pero **el código sigue
ahí**. Si en una semana nadie lo echa de menos, se borra de verdad; si hace falta,
se reactiva en un minuto.

**Reactivar un módulo:**

1. Sin desplegar — variable de entorno en Railway::

       AGENCY_HIDDEN_MODULES=finance,reports        # deja fuera el resto
       AGENCY_HIDDEN_MODULES=                       # reactiva TODOS

2. Permanente — quitar su clave de ``HIDDEN_MODULES`` aquí **y** de
   ``frontend/src/lib/hidden-modules.ts``. Las dos listas deben coincidir; hay un
   test (``tests/test_hidden_modules.py``) que falla si divergen.

La lista vive en un solo sitio a propósito: cuando el mismo estado se escribe en
varios sitios, uno se queda atrás (pasó con los 4 mapas de estado de rentabilidad
y con los defaults de poda de Vigil).
"""
from __future__ import annotations

import os

# Módulos ocultos por decisión de producto, con sus llamadas en la ventana
# 2 jun – 17 ago 2026 (77 días) para que se vea de dónde sale cada uno.
HIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "finance",        # 0 llamadas — 8 páginas: ingresos, gastos, impuestos,
                          #              previsiones, asesor, importación, balance
        "holded",         # 26 — dos visitas en 77 días
        "cfo",            # 0
        "reports",        # 0 — el informe mensual se hace fuera de la aplicación
        "proposals",      # 30, solo el listado: nunca se creó una propuesta
        "leads",          # 37 — Pipeline
        "growth",         # 4 — Buffer de ideas
        "my_week",        # 12 — 592 líneas de backend para 12 llamadas
        "automations",    # 0 — ninguna regla llegó a ejecutarse
        "vault",          # 0
        "billing",        # 0
        "capacity",       # solo frontend
        "executive",      # solo frontend
        # OJO — "discord" oculta la PANTALLA, pero su router sigue registrado
        # (ver _CORE_ROUTERS en main.py). El dashboard lee /api/discord/settings
        # para saber si ofrecer "Enviar a Discord" en el Resumen Diario, y ese
        # envío sí se usa: 43 veces en 77 días. Ocultar una pantalla y apagar
        # una API son cosas distintas; aquí solo queríamos lo primero.
        "discord",        # 13 visitas a la pantalla de ajustes del webhook
        "communications", # 0
        "resources",      # 0
        "evidence",       # 0 — los 7 endpoints
        "core_updates",   # 0 — con él se van sklearn y numpy de la imagen
        "invitations",    # 0 — sin un solo llamador en el frontend
        "export",         # 0
    }
)

# Deliberadamente NO ocultos, aunque las cifras invitaran a ello:
#   search (0 llamadas) — es la paleta ⌘K del shell, no una pantalla. Quitarla
#       dejaría el atajo roto DENTRO de las páginas que sí conservamos.
#   pm (30) — el panel "Asistente PM" está incrustado en el dashboard.


def _from_env() -> frozenset[str] | None:
    """Lee ``AGENCY_HIDDEN_MODULES`` si está definida.

    Cadena vacía es una respuesta válida y significa "no ocultes nada" — por eso
    se comprueba ``is None`` y no la veracidad del valor.
    """
    raw = os.environ.get("AGENCY_HIDDEN_MODULES")
    if raw is None:
        return None
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def hidden_modules() -> frozenset[str]:
    """Módulos ocultos ahora mismo (la variable de entorno manda)."""
    override = _from_env()
    return HIDDEN_MODULES if override is None else override


def is_hidden(module: str) -> bool:
    return module in hidden_modules()


def is_enabled(module: str) -> bool:
    return not is_hidden(module)
