"""Historial mensual por consulta de Search Console: reglas sin BD (meses
completos, qué se pide a Google, posición ponderada y petición a la API)."""

from __future__ import annotations

from datetime import date, timedelta

import httplib2
import pytest
from googleapiclient.errors import HttpError

from backend.services import gsc_detail_service as detail
from backend.services import gsc_service
from backend.services.gsc_service import GscAuthError, GscSiteError


class _FakeService:
    def __init__(self, pages=None, error=None):
        self.pages = list(pages or [])
        self.error = error
        self.bodies: list[dict] = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):  # noqa: N803 — nombre de la API de Google
        self.bodies.append(dict(body))
        return self

    def execute(self):
        if self.error is not None:
            raise self.error
        return {"rows": self.pages.pop(0)} if self.pages else {}


@pytest.fixture
def fake(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(detail, "_sleep", sleeps.append)

    def install(service):
        monkeypatch.setattr(gsc_service, "_service", lambda _token: service)
        return sleeps
    return install


def test_meses_y_suelo_del_historial():
    assert detail.add_months(date(2026, 10, 1), -15) == date(2025, 7, 1)
    assert detail.add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert detail.add_months(date(2025, 12, 1), 1) == date(2026, 1, 1)
    assert detail.month_end(date(2028, 2, 1)) == date(2028, 2, 29)
    # 16 meses contando el actual.
    assert detail.history_floor(date(2026, 10, 22)) == date(2025, 7, 1)
    assert detail.history_floor(date(2026, 1, 3)) == date(2024, 10, 1)


def test_cobertura_el_primer_dia_guardado_o_la_retencion():
    today = date(2026, 10, 22)
    last = date(2026, 10, 19)
    retention = detail._retention_cutoff(last, today) + timedelta(days=1)
    assert detail.coverage_start(None, last, today) == retention
    assert detail.coverage_start(retention - timedelta(days=30), last, today) == retention
    assert detail.coverage_start(date(2026, 8, 3), last, today) == date(2026, 8, 3)
    assert detail.coverage_start(date(2026, 8, 3), None, today) is None


def test_solo_cuentan_los_meses_enteros_con_datos_finales():
    # Del 1 de julio al 30 de septiembre: julio, agosto y septiembre.
    assert detail.complete_months(date(2026, 7, 1), date(2026, 9, 30)) == [
        date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
    # Empieza el 2 de julio: julio no está entero. Falta el 30 de septiembre: tampoco.
    assert detail.complete_months(date(2026, 7, 2), date(2026, 9, 29)) == [date(2026, 8, 1)]
    assert detail.complete_months(None, date(2026, 9, 30)) == []
    assert detail.complete_months(date(2026, 7, 1), None) == []


def test_a_google_se_piden_los_meses_que_el_detalle_no_tiene_enteros():
    today = date(2026, 10, 22)
    coverage, last = date(2026, 6, 24), date(2026, 10, 19)
    months = detail.backfill_months(coverage, last, today)
    # De julio de 2025 (16 meses) a junio de 2026, que empieza antes de la cobertura.
    assert months[0] == date(2025, 7, 1) and months[-1] == date(2026, 6, 1) and len(months) == 12
    # Ninguno se solapa con los que salen del detalle y no queda hueco entre ellos.
    from_detail = detail.complete_months(coverage, last)
    assert not set(months) & set(from_detail)
    assert detail.add_months(months[-1], 1) == from_detail[0]
    assert detail.backfill_months(None, last, today) == []


def test_un_mes_de_google_guarda_la_posicion_ponderada():
    rows = [detail.MonthRow("zapatos", 3, 10, 2.0), detail.MonthRow("botas", 1, 30, 6.0),
            detail.MonthRow("zapatos", 1, 30, 6.0)]
    values = {v["query"]: v for v in detail.month_values(date(2026, 5, 1), "s", rows)}
    assert values["botas"]["weighted_position_sum"] == pytest.approx(180.0)
    z = values["zapatos"]
    assert (z["clicks"], z["impressions"], z["month"]) == (4, 40, date(2026, 5, 1))
    # Recalculada: (2×10 + 6×30) / 40 = 5.
    assert z["weighted_position_sum"] / z["impressions"] == pytest.approx(5.0)


def test_el_mes_se_pide_por_consulta_sin_dia_y_paginando(fake):
    service = _FakeService(pages=[
        [{"keys": [f"q{i}"], "clicks": 1, "impressions": 10, "position": 3.0} for i in range(25000)],
        [{"keys": ["ultima"], "clicks": 2, "impressions": 5, "position": 1.5}],
    ])
    sleeps = fake(service)

    rows = detail._query_month_sync("v1:x", "sc-domain:a.com", date(2026, 5, 1), date(2026, 5, 31))

    assert len(rows) == 25001 and rows[-1] == detail.MonthRow("ultima", 2, 5, 1.5)
    assert [b["startRow"] for b in service.bodies] == [0, 25000] and sleeps == [0.2]
    body = service.bodies[0]
    assert body["dimensions"] == ["query"]
    assert (body["startDate"], body["endDate"], body["type"], body["dataState"], body["rowLimit"]) == (
        "2026-05-01", "2026-05-31", "web", "final", 25000)


def test_el_mes_traduce_los_errores_de_google(fake):
    fake(_FakeService(error=HttpError(httplib2.Response({"status": 403}), b"{}")))
    with pytest.raises((GscAuthError, GscSiteError)):
        detail._query_month_sync("v1:x", "s", date(2026, 5, 1), date(2026, 5, 31))
