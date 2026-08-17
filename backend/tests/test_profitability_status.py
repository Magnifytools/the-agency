"""Regresión: clasificación de rentabilidad (auditoría ago 2026).

Dos defectos encontrados en producción, ambos por la misma causa: con el
presupuesto a 0 el ``margin_pct`` se fuerza a 0, y ese 0 se leía como un juicio
sobre el margen en vez de como "no hay datos".

  - Mosquita Digital: 0 € tarifa, 0 € coste, 0 h imputadas. Sin actividad
    ninguna, y el dashboard lo anunciaba como "En riesgo".
  - Taxfix: 0 € tarifa, 56 € de coste, margen real -56 €. Un cliente que pierde
    dinero anunciado como "En riesgo" en el dashboard y como "No rentable" en
    su propia ficha — dos pantallas, dos respuestas, ninguna cierta.

Los valores de estos tests son los reales de producción el 17 ago 2026.
"""
from __future__ import annotations

import pytest

from backend.schemas.dashboard import ProfitabilityStatus
from backend.services.profitability import classify_profitability

# Umbrales tal y como los usa cada pantalla (distintos a propósito).
DASHBOARD = {"profitable_at_pct": 20}
CLIENT_TAB = {"profitable_at_pct": 30, "unprofitable_below_pct": 10}


class TestSinTarifaConfigurada:
    """budget <= 0 nunca es un juicio sobre el margen."""

    def test_cliente_sin_tarifa_ni_actividad_es_no_data(self):
        """Mosquita Digital. Antes: at_risk."""
        assert classify_profitability(
            budget=0.0, margin=0.0, margin_pct=0.0, **DASHBOARD
        ) == ProfitabilityStatus.no_data

    def test_cliente_sin_tarifa_con_coste_es_no_data(self):
        """Taxfix. Antes: at_risk en dashboard, unprofitable en la ficha.

        No se puede afirmar que pierda dinero: lo que falta es la tarifa.
        Decirlo es más honesto que deducir una pérdida de un dato ausente.
        """
        assert classify_profitability(
            budget=0.0, margin=-56.0, margin_pct=0.0, **DASHBOARD
        ) == ProfitabilityStatus.no_data

    def test_misma_respuesta_en_las_dos_pantallas(self):
        """El bug daba veredictos distintos según dónde mirases."""
        args = {"budget": 0.0, "margin": -56.0, "margin_pct": 0.0}
        assert (
            classify_profitability(**args, **DASHBOARD)
            == classify_profitability(**args, **CLIENT_TAB)
            == ProfitabilityStatus.no_data
        )

    def test_presupuesto_negativo_tambien_es_no_data(self):
        assert classify_profitability(
            budget=-10.0, margin=5.0, margin_pct=50.0, **DASHBOARD
        ) == ProfitabilityStatus.no_data


class TestElSignoDelMargenManda:
    """Con tarifa, perder dinero es 'no rentable' aunque el % diga otra cosa."""

    def test_margen_negativo_es_unprofitable(self):
        assert classify_profitability(
            budget=1000.0, margin=-200.0, margin_pct=-20.0, **DASHBOARD
        ) == ProfitabilityStatus.unprofitable

    def test_margen_negativo_gana_a_un_pct_incoherente(self):
        """Blindaje: si el % viniera mal calculado, el signo del margen decide."""
        assert classify_profitability(
            budget=1000.0, margin=-1.0, margin_pct=99.0, **DASHBOARD
        ) == ProfitabilityStatus.unprofitable


class TestUmbralesPreservados:
    """El refactor no debe mover los umbrales de ninguna de las dos pantallas."""

    @pytest.mark.parametrize(
        "margin_pct,esperado",
        [
            (80.7, ProfitabilityStatus.profitable),   # Sage, real
            (93.7, ProfitabilityStatus.profitable),   # Kinetic, real
            (20.0, ProfitabilityStatus.profitable),   # justo en el umbral
            (19.9, ProfitabilityStatus.at_risk),
            (0.0, ProfitabilityStatus.at_risk),       # margen 0 con tarifa real
        ],
    )
    def test_dashboard(self, margin_pct, esperado):
        margin = 1000.0 * margin_pct / 100
        assert classify_profitability(
            budget=1000.0, margin=margin, margin_pct=margin_pct, **DASHBOARD
        ) == esperado

    @pytest.mark.parametrize(
        "margin_pct,esperado",
        [
            (30.0, ProfitabilityStatus.profitable),   # justo en el umbral
            (29.9, ProfitabilityStatus.at_risk),
            (10.0, ProfitabilityStatus.at_risk),
            (9.9, ProfitabilityStatus.unprofitable),  # umbral propio de la ficha
        ],
    )
    def test_ficha_cliente(self, margin_pct, esperado):
        margin = 1000.0 * margin_pct / 100
        assert classify_profitability(
            budget=1000.0, margin=margin, margin_pct=margin_pct, **CLIENT_TAB
        ) == esperado
