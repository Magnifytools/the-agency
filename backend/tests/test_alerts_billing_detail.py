"""Regresión: el `None€` de las alertas del dashboard (auditoría ago 2026).

`GET /api/dashboard/alerts-summary` construía el detalle de facturación con
``f"{p.name}: {p.billing_amount}€"``. ``billing_amount`` es nullable, así que
un proyecto sin importe configurado renderizaba el ``None`` de Python tal cual.

En producción se leía, literalmente:

    "Taxfix ES+UK WordPress & Content Support: None€, SEO Retainer SSM: 950.00€"

Dos líneas más arriba el total sí protegía el ``None`` (``or 0``), lo que hacía
el fallo más difícil de ver: el título cuadraba y solo mentía el detalle.
"""
from __future__ import annotations

import pytest

from backend.services.profitability import format_billing_detail


class TestFormatBillingDetail:
    def test_importe_ausente_no_renderiza_none(self):
        """El caso exacto que se veía en el dashboard de producción."""
        linea = format_billing_detail("Taxfix ES+UK WordPress & Content Support", None)
        assert "None" not in linea
        assert linea == "Taxfix ES+UK WordPress & Content Support: sin importe configurado"

    def test_importe_ausente_no_se_finge_como_cero(self):
        """'Sin configurar' y '0 €' piden acciones distintas; no se mezclan."""
        assert "0.00€" not in format_billing_detail("Proyecto", None)

    def test_importe_presente_con_dos_decimales(self):
        assert format_billing_detail("SEO Retainer SSM", 950) == "SEO Retainer SSM: 950.00€"

    def test_cero_explicito_si_se_renderiza(self):
        """Un 0 configurado a mano sí es un dato: se muestra."""
        assert format_billing_detail("Proyecto", 0) == "Proyecto: 0.00€"

    @pytest.mark.parametrize("amount", [950, 950.0, 950.004])
    def test_acepta_int_float_y_decimal_de_la_columna_numeric(self, amount):
        """La columna es NUMERIC: asyncpg puede devolver Decimal, int o float."""
        assert format_billing_detail("P", amount) == "P: 950.00€"
