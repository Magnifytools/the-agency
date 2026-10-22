"""Piezas puras de los leads por landing (`services/ga4_leads.py`) y de las
importaciones de The Engine (sin base de datos). Lo de verdad, contra Postgres
real, está en `tests/integration/test_ga4_leads_integration.py` y
`tests/integration/test_engine_import.py`."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.scripts import import_engine_leads as il
from backend.scripts import import_engine_positions as ip
from backend.services.ga4_leads import (
    EventMatcher, LeadRow, aggregate_report_rows, clean_channel, clean_landing, clean_lead_events, events_key,
    merge_rows, report_body, strip_tracking,
)

FIXTURES = Path(__file__).parent / "fixtures" / "engine"


def test_eventos_de_lead_validos_e_invalidos():
    assert clean_lead_events(None) == ["generate_lead"]
    assert clean_lead_events([" generate_lead ", "generate_lead_*", "generate_lead", ""]) == [
        "generate_lead", "generate_lead_*"]
    for bad in ([], [""], ["1lead"], ["lead-form"], ["a*b"], ["x" * 41], [3], "generate_lead",
                [f"e{i}" for i in range(21)]):
        with pytest.raises(ValueError):
            clean_lead_events(bad)


def test_nombre_exacto_y_prefijo():
    match = EventMatcher(["generate_lead", "form_*"])
    assert match("generate_lead") and match("form_") and match("form_contacto")
    assert not match("generate_lead_cpe") and not match("Generate_lead") and not match(None)
    assert EventMatcher(["generate_lead_*"])("generate_lead_cpe")
    assert events_key(["b", "a", "a"]) == events_key(["a", "b"]) == '["a","b"]'


def test_landing_sin_seguimiento_y_con_host():
    assert clean_landing("/cpe/?utm_source=x&a=1&fbclid=2&UTM_Campaign=y", "GO.acme.com") == "go.acme.com/cpe/?a=1"
    assert clean_landing("/cpe/?gclid=1&gbraid=2&srsltid=3") == "/cpe/"
    assert clean_landing("https://www.acme.com/a?ltk_fcm=1#top") == "www.acme.com/a"
    assert clean_landing("https://www.acme.com/a", "acme.com") == "acme.com/a"
    assert clean_landing("", "acme.com") == "acme.com/"
    assert clean_landing("(not set)", "acme.com") == "(not set)"
    assert clean_landing("/x/", "(not set)") == "/x/"
    assert len(clean_landing("/" + "a" * 3000, "acme.com")) == 2000
    # El orden de los parámetros que quedan no cambia.
    assert strip_tracking("b=2&utm_id=1&a=1") == "b=2&a=1"


def test_canal():
    assert clean_channel("Organic Search") == "Organic Search"
    assert clean_channel("unknown") == clean_channel("") == clean_channel(None) == "(not set)"
    assert len(clean_channel("x" * 100)) == 64


def test_peticion_a_ga4_filtra_los_eventos():
    body = report_body(["generate_lead"], date(2026, 1, 1), date(2026, 1, 31), offset=100000)
    assert [d["name"] for d in body["dimensions"]] == [
        "date", "landingPagePlusQueryString", "hostName", "sessionDefaultChannelGroup", "eventName"]
    assert body["metrics"] == [{"name": "eventCount"}] and body["offset"] == 100000
    assert body["dimensionFilter"]["filter"]["stringFilter"]["matchType"] == "EXACT"
    both = report_body(["generate_lead", "form_*"], date(2026, 1, 1), date(2026, 1, 31))
    kinds = [e["filter"]["stringFilter"]["matchType"] for e in both["dimensionFilter"]["orGroup"]["expressions"]]
    assert kinds == ["EXACT", "BEGINS_WITH"]


def test_filas_de_ga4_se_juntan_por_dia_landing_y_canal():
    def row(day, landing, host, channel, event, count):
        return {"dimensionValues": [{"value": v} for v in (day, landing, host, channel, event)],
                "metricValues": [{"value": str(count)}]}
    out = aggregate_report_rows([
        row("20261001", "/cpe/?fbclid=A", "acme.com", "Paid Social", "generate_lead", 2),
        row("20261001", "/cpe/?fbclid=B", "acme.com", "Paid Social", "generate_lead", 3),
        row("20261001", "/cpe/", "go.acme.com", "Paid Social", "generate_lead", 1),
        row("20261001", "/cpe/", "acme.com", "Paid Social", "page_view", 99),
        row("20261002", "/", "acme.com", "", "generate_lead", 1),
    ], EventMatcher(["generate_lead"]))
    assert out == [
        LeadRow(date(2026, 10, 1), "acme.com/cpe/", "Paid Social", 5),
        LeadRow(date(2026, 10, 1), "go.acme.com/cpe/", "Paid Social", 1),
        LeadRow(date(2026, 10, 2), "acme.com/", "(not set)", 1),
    ]
    assert merge_rows([LeadRow(date(2026, 1, 1), "/", "x", 0)]) == []


def test_consultas_de_engine_se_normalizan_como_search_console():
    assert ip.normalize_query("  TSAF   a Distancia ") == "tsaf a distancia"


def test_csv_de_posiciones_se_agrupa_por_mes():
    report = ip.PositionsReport(dry_run=True)
    acc = ip.read_csv(FIXTURES / "keyword_positions.csv", report)
    assert (report.rows_read, report.rows_skipped) == (11, 2)
    assert (report.first_date, report.last_date) == (date(2024, 12, 4), date(2025, 10, 3))
    # "TSAF" y "tsaf" son la misma consulta; posición ponderada por impresiones.
    assert acc[("tsaf", date(2024, 12, 1))] == [2, 10, 40.0]
    assert acc[("tsaf a distancia", date(2024, 12, 1))] == [1, 30, 300.0]
    assert acc[("tsaf", date(2025, 1, 1))] == [6, 40, 200.0]
    assert ("botas", date(2025, 1, 1)) not in acc


def test_csv_sin_columnas_aborta(tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("keyword,date\nx,2025-01-01\n", encoding="utf-8")
    with pytest.raises(ip.ImportAborted, match="position"):
        ip.read_csv(bad, ip.PositionsReport(dry_run=True))
    with pytest.raises(il.ImportAborted, match="landing_page"):
        il.read_csv(bad, EventMatcher(["generate_lead"]), il.LeadsReport(dry_run=True))


def test_csv_de_leads_se_normaliza_como_ga4():
    report = il.LeadsReport(dry_run=True)
    rows = il.read_csv(FIXTURES / "lead_attribution.csv", EventMatcher(["generate_lead_*"]), report)
    assert (report.rows_read, report.rows_skipped, report.rows_other_events) == (9, 2, 1)
    assert LeadRow(date(2025, 8, 10), "go.acme.com/cpe/", "Paid Search", 5) in rows
    assert LeadRow(date(2025, 8, 10), "acme.com/cpe/", "Organic Search", 1) in rows
    assert LeadRow(date(2025, 8, 11), "/blog/x/?ref=1", "(not set)", 4) in rows
