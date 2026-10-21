"""Detalle de Search Console (consultas y páginas): lógica sin BD."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from backend.services import gsc_detail_service as detail
from backend.services import gsc_service
from backend.services.gsc_service import GscAuthError, GscSiteError

ROOT = Path(__file__).resolve().parents[2]


class _FakeService:
    """Imita `searchanalytics().query(...).execute()` y apunta cada cuerpo pedido."""

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


def _rows(n, *, day="2026-10-01", prefix="q"):
    return [{"keys": [day, f"{prefix}{i}"], "clicks": 1, "impressions": 10, "position": 3.0} for i in range(n)]


@pytest.fixture
def fake(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(detail, "_sleep", sleeps.append)

    def install(service):
        monkeypatch.setattr(gsc_service, "_service", lambda _token: service)
        return sleeps
    return install


def test_pagina_hasta_que_una_pagina_viene_incompleta(fake):
    service = _FakeService(pages=[_rows(25000), _rows(25000, prefix="r"), _rows(3, prefix="s")])
    sleeps = fake(service)

    rows = detail._query_dim_sync("v1:x", "sc-domain:a.com", date(2026, 10, 1), date(2026, 10, 14), "query")

    assert len(rows) == 50003
    assert [b["startRow"] for b in service.bodies] == [0, 25000, 50000]
    assert sleeps == [0.2, 0.2]
    body = service.bodies[0]
    assert body["dimensions"] == ["date", "query"]
    assert (body["type"], body["dataState"], body["rowLimit"]) == ("web", "final", 25000)
    assert (body["startDate"], body["endDate"]) == ("2026-10-01", "2026-10-14")


def test_una_sola_pagina_si_vienen_menos_de_25000(fake):
    service = _FakeService(pages=[_rows(10)])
    sleeps = fake(service)

    rows = detail._query_dim_sync("v1:x", "sc-domain:a.com", date(2026, 10, 1), date(2026, 10, 1), "query")

    assert len(rows) == 10 and len(service.bodies) == 1 and sleeps == []
    assert rows[0] == detail.DetailRow(date(2026, 10, 1), "q0", 1, 10, 3.0)


def test_sin_filas_no_sigue_pidiendo(fake):
    service = _FakeService(pages=[])
    fake(service)
    assert detail._query_dim_sync("v1:x", "s", date(2026, 10, 1), date(2026, 10, 1), "page") == []
    assert len(service.bodies) == 1


def test_las_paginas_largas_se_recortan_y_se_unen_si_coinciden(fake):
    base = "https://a.com/" + "x" * 2100
    service = _FakeService(pages=[[
        {"keys": ["2026-10-01", base + "1"], "clicks": 2, "impressions": 10, "position": 2.0},
        {"keys": ["2026-10-01", base + "2"], "clicks": 1, "impressions": 30, "position": 6.0},
    ]])
    fake(service)

    rows = detail._query_dim_sync("v1:x", "s", date(2026, 10, 1), date(2026, 10, 1), "page")

    assert len(rows) == 1
    row = rows[0]
    assert len(row.key) == detail.MAX_PAGE_LENGTH
    # Clics e impresiones se suman; posición ponderada por impresiones.
    assert (row.clicks, row.impressions) == (3, 40)
    assert row.position == pytest.approx((2.0 * 10 + 6.0 * 30) / 40)


def _http_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}")


@pytest.mark.parametrize("error, expected", [
    (_http_error(403), GscSiteError("no_access")),
    (_http_error(404), GscSiteError("not_found")),
    (_http_error(429), GscSiteError("rate_limited")),
    (_http_error(500), GscSiteError("api_error")),
    (_http_error(401), GscAuthError("unauthorized")),
    (RefreshError("invalid_grant"), GscAuthError("invalid_grant")),
])
def test_los_errores_de_google_se_traducen(fake, error, expected):
    fake(_FakeService(error=error))
    with pytest.raises(type(expected)) as info:
        detail._query_dim_sync("v1:x", "s", date(2026, 10, 1), date(2026, 10, 1), "query")
    if isinstance(expected, GscSiteError):
        assert info.value.code == expected.code


def test_primera_importacion_120_dias_en_tramos_de_14():
    today = date(2026, 10, 22)
    chunks, backfill = detail.plan_chunks(backfilled=False, last_data_date=None, today=today)

    assert backfill is True
    end = date(2026, 10, 21)
    assert chunks[0][0] == end - timedelta(days=119)
    assert chunks[-1][1] == end
    assert all((b - a).days + 1 <= 14 for a, b in chunks)
    assert all((b - a).days + 1 == 14 for a, b in chunks[:-1])
    # Contiguos y sin solapes: 120 días exactos.
    assert all(chunks[i][1] + timedelta(days=1) == chunks[i + 1][0] for i in range(len(chunks) - 1))
    assert sum((b - a).days + 1 for a, b in chunks) == 120
    assert len(chunks) == 9


def test_despues_solo_la_cola_de_7_dias():
    chunks, backfill = detail.plan_chunks(backfilled=True, last_data_date=date(2026, 10, 19), today=date(2026, 10, 22))

    assert backfill is False
    assert chunks == [(date(2026, 10, 12), date(2026, 10, 21))]


def test_la_cola_nunca_sale_de_la_ventana_de_120_dias():
    today = date(2026, 10, 22)
    chunks, _ = detail.plan_chunks(backfilled=True, last_data_date=date(2026, 1, 1), today=today)
    assert chunks[0][0] == date(2026, 10, 21) - timedelta(days=119)


def test_retencion_120_dias_desde_el_ultimo_dato_con_margen_si_se_para():
    today = date(2026, 10, 22)
    assert detail._retention_cutoff(date(2026, 10, 19), today) == date(2026, 10, 19) - timedelta(days=120)
    # Propiedad parada hace meses: la ventana avanza igual (máximo 7 días de margen).
    assert detail._retention_cutoff(date(2026, 5, 1), today) == date(2026, 10, 14) - timedelta(days=120)


@pytest.mark.parametrize("result, code", [
    ({"status": "reconnect_required", "synced": 0, "failed": 1, "skipped": 0}, "reconnect_required"),
    ({"status": "ok", "synced": 1, "failed": 1, "skipped": 0}, "partial_failure"),
    ({"status": "ok", "synced": 1, "failed": 0, "skipped": 3}, None),
])
async def test_el_job_informa_reconexion_y_fallos_parciales(monkeypatch, result, code):
    from backend.services.job_runtime import JobFailure
    from backend.startup import background_tasks

    async def fake_sync(_factory):
        return result
    monkeypatch.setattr(detail, "sync_all_detail", fake_sync)
    if code:
        with pytest.raises(JobFailure, match=code):
            await background_tasks._gsc_detail_sync_once()
    else:
        await background_tasks._gsc_detail_sync_once()


def test_el_job_usa_el_lock_17_y_la_misma_puerta_que_gsc():
    from backend.services.job_catalog import job_definitions

    definitions = {d.spec.key: d for d in job_definitions()}
    spec = definitions["gsc_detail"].spec
    assert (spec.lock_id, spec.interval_seconds, spec.timeout_seconds, spec.retry_seconds) == (17, 86400, 3600, 3600)
    assert definitions["gsc_detail"].paused_reason == definitions["gsc"].paused_reason
    locks = [d.spec.lock_id for d in job_definitions()]
    assert len(locks) == len(set(locks))


# ── Las consultas y páginas no van a la IA (lo promete la política de privacidad) ──

# También el historial mensual por consulta y los grupos de URL del Control SEO.
_FORBIDDEN = re.compile(
    r"GscQueryDaily|GscPageDaily|GscQueryMonthly|gsc_query_daily|gsc_page_daily|gsc_query_monthly"
    r"|gsc_detail_service|seo_control|client_seo|seo_page_groups|query_history"
)


def _ai_paths() -> list[Path]:
    services = ROOT / "backend" / "services"
    paths = {
        services / name for name in (
            "ai_utils.py", "digest_generator.py", "digest_generation.py", "digest_collector.py",
            "task_draft.py", "client_advisor.py", "client_share_links.py", "daily_parser.py",
            "email_drafter.py",
        )
    }
    paths.add(ROOT / "backend" / "api" / "routes" / "advisor.py")
    # Cualquier servicio que llame a Claude.
    paths |= {p for p in services.glob("*.py") if "ai_utils" in p.read_text(encoding="utf-8")}
    paths |= set((ROOT / "mcp-server" / "agency_mcp").rglob("*.py"))
    return sorted(paths)


def test_la_guardia_reconoce_el_historial_y_los_grupos():
    for name in ("GscQueryMonthly", "gsc_query_monthly", "seo_page_groups", "query_history"):
        assert _FORBIDDEN.search(f"x = {name}")


def test_el_detalle_de_search_console_no_llega_a_la_ia():
    paths = _ai_paths()
    assert ROOT / "backend" / "services" / "digest_generator.py" in paths
    assert any("mcp-server" in str(p) for p in paths)
    offenders = [str(p.relative_to(ROOT)) for p in paths
                 if p.exists() and _FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
