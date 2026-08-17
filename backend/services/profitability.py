"""Clasificación de rentabilidad de un cliente.

Vivía duplicada e inline en dos rutas (`dashboard.profitability` y
`client_dashboard`), cada una con su propio orden de comprobaciones. Las dos
compartían el mismo defecto: con el presupuesto a 0 el `margin_pct` se fuerza
a 0, así que un cliente **sin tarifa configurada** acababa clasificado como si
se hubiera juzgado su margen — "En riesgo" en el dashboard y "No rentable" en
la ficha del cliente. Un cliente que pierde dinero de verdad (margen negativo
con presupuesto 0) esquivaba además la rama `unprofitable` por la misma razón.

El orden de decisión es el que importa y por eso vive en un solo sitio:

1. Sin tarifa no hay margen que juzgar  -> ``no_data``.
2. Con tarifa, manda el SIGNO del margen -> ``unprofitable``.
3. Solo entonces se aplican los umbrales de porcentaje.

Los umbrales siguen siendo distintos en cada pantalla (era así antes de
extraer esto y cambiarlos es una decisión de producto, no de refactor), por
eso se pasan como parámetros en vez de fijarlos aquí.
"""
from __future__ import annotations

from typing import Optional

from backend.schemas.dashboard import ProfitabilityStatus


def format_billing_detail(project_name: str, billing_amount: Optional[float]) -> str:
    """Una línea del detalle de la alerta de facturación.

    ``billing_amount`` es nullable. Sin guarda, el f-string original
    (``f"{p.name}: {p.billing_amount}€"``) renderizaba el ``None`` de Python
    tal cual y en producción se leía "Taxfix ES+UK ...: None€".

    Un importe ausente se dice, no se finge con un 0 €: son cosas distintas y
    la acción que pide el usuario también (configurar la tarifa, no cobrar 0).
    """
    if billing_amount is None:
        return f"{project_name}: sin importe configurado"
    return f"{project_name}: {float(billing_amount):.2f}€"


def classify_profitability(
    *,
    budget: float,
    margin: float,
    margin_pct: float,
    profitable_at_pct: float,
    unprofitable_below_pct: float = 0.0,
) -> ProfitabilityStatus:
    """Clasifica la rentabilidad de un cliente en el periodo.

    Args:
        budget: tarifa del periodo. <= 0 significa "sin configurar", NO "gratis".
        margin: ``budget - coste``, en euros. Su signo manda sobre el porcentaje.
        margin_pct: margen en % sobre el presupuesto. No es fiable si budget <= 0.
        profitable_at_pct: a partir de qué % se considera rentable.
        unprofitable_below_pct: por debajo de qué % se considera no rentable.
    """
    if budget <= 0:
        return ProfitabilityStatus.no_data
    if margin < 0 or margin_pct < unprofitable_below_pct:
        return ProfitabilityStatus.unprofitable
    if margin_pct >= profitable_at_pct:
        return ProfitabilityStatus.profitable
    return ProfitabilityStatus.at_risk
