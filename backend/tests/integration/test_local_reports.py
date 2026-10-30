"""Informe SEO local por la API, contra Postgres real: configurar, calcular, subir
la ficha y el rastreo, editar, redactar (IA falsa), generar, entregar y versionar.

Google y Chromium no se tocan: `gsc_live.query` y `render.render` se sustituyen.
"""
from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.core.rate_limiter import gsc_live_limiter
from backend.db.models import Client, ClientLocalReport, ClientStatus, Project, Task, TaskStatus
from backend.services import gsc_live
from backend.services.local_report import render, service

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "local_report_2026_10"
TODAY = date(2026, 11, 5)


@pytest_asyncio.fixture(autouse=True)
async def _fakes(monkeypatch):
    gsc_live_limiter._limiter._requests.clear()

    async def fake_query(db, client, *, start_date, end_date, dimensions, filters, row_limit, start_row):
        rows = []
        if dimensions == ["query"]:
            rows = [{"keys": {"query": "caravantes toledo"}, "clicks": 200, "impressions": 3000, "ctr": None,
                     "position": 2.0},
                    {"keys": {"query": "comuniones en toledo"}, "clicks": 6, "impressions": 19, "ctr": None,
                     "position": 10.8}]
        elif dimensions == ["page"]:
            rows = [{"keys": {"page": "https://cigarraldecaravantes.com/"}, "clicks": 500, "impressions": 9000,
                     "ctr": None, "position": 3.0}]
        elif dimensions == ["date"]:
            rows = [{"keys": {"date": "2026-09-15"}, "clicks": 356, "impressions": 6562, "ctr": None,
                     "position": 3.0}]
        total = {"clicks": 400, "impressions": 6000, "ctr": 0.066, "position": 3.1}
        return {"rows": rows, "totals": total, "has_more": False, "next_start_row": None,
                "data_available_until": end_date.isoformat()}

    async def fake_render(name, datos, roadmap):
        pdf = b"%PDF-1.4 falso"
        html = ('<section class="section" id="resumen">' + '<svg class="executive-icon"></svg>' * 8 + "</section>"
                + '<section class="section"></section>' * 10
                + f'<script id="embedded-pdf" type="application/pdf">{base64.b64encode(pdf).decode()}</script>')
        rendered = render.Rendered("Cigarral_Seguimiento_Mensual_2026-Octubre", html.encode(), pdf, {})
        rendered.checks = render.check(rendered.html, pdf, datos, roadmap)
        return rendered

    monkeypatch.setattr(gsc_live, "query", fake_query)
    monkeypatch.setattr(service.render, "render", fake_render)
    monkeypatch.setattr(service, "business_today", lambda: TODAY)
    monkeypatch.setattr("backend.api.routes.local_reports.business_today", lambda: TODAY)
    yield
    gsc_live_limiter._limiter._requests.clear()


@pytest_asyncio.fixture
async def cigarral(db_session):
    client = Client(name="Cigarral de Caravantes", status=ClientStatus.active,
                    gsc_url="https://cigarraldecaravantes.com/", brand_terms=["caravantes", "carabante"])
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Cigarral de Caravantes · SEO local", client_id=client.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add_all([
        Task(title="E1 - Redirecciones internas", client_id=client.id, project_id=project.id,
             status=TaskStatus.completed, completed_at=datetime(2026, 10, 27, 10, 0)),
        Task(title="E1 - Optimización GBP", client_id=client.id, project_id=project.id,
             status=TaskStatus.waiting, waiting_for="Laura: horarios y categoría"),
    ])
    await db_session.commit()
    return client


async def _setup(admin_client, client_id):
    res = await admin_client.post(f"/api/clients/{client_id}/local-report/config", json={"template": "cigarral"})
    assert res.status_code == 201, res.text
    res = await admin_client.post(f"/api/clients/{client_id}/local-report/reports", json={})
    assert res.status_code == 201, res.text
    return res.json()


async def test_flujo_completo(admin_client, cigarral, db_session):
    base = f"/api/clients/{cigarral.id}/local-report"
    report = await _setup(admin_client, cigarral.id)
    rid = report["id"]
    # Por defecto, el mes natural anterior.
    assert (report["period_start"], report["period_end"]) == ("2026-10-01", "2026-10-31")
    assert report["datos"]["gsc"]["clics_mes"] == 400
    assert report["datos"]["informe"]["modo"] == "Datos de octubre de 2026"
    october = {t["nombre"]: t for t in report["roadmap"]["meses"]["2026-10"]["tareas"]}
    assert october["Redirecciones internas"]["estado"] == "hecho"
    assert october["Optimización GBP"]["estado"] == "bloqueado"
    assert any("ficha de Google" in w for w in report["warnings"])
    assert len(report["text_keys"]) == 29

    overview = (await admin_client.get(base)).json()
    assert overview["config"]["template"] == "cigarral" and overview["reports"][0]["id"] == rid

    # Ficha de Google del periodo (el archivo es del 1 al 25: se acepta).
    name = "GBP_restaurante_2026-10-01_2026-10-25.csv"
    res = await admin_client.post(f"{base}/reports/{rid}/sources", data={"kind": "gbp_actual"},
                                  files={"file": (name, (FIXTURES / name).read_bytes(), "text/csv")})
    assert res.status_code == 201, res.text
    google = res.json()["datos"]["google"]
    assert (google["vistas_perfil"], google["clics_llamada"], google["indicaciones"]) == (2628, 64, 268)
    name = "internal_redirection_3xx_inlinks_2026-10.csv"
    res = await admin_client.post(f"{base}/reports/{rid}/sources", data={"kind": "rastreo"},
                                  files={"file": (name, (FIXTURES / name).read_bytes(), "text/csv")})
    assert res.json()["datos"]["tecnico"]["enlaces_redirigen"] == 2
    res = await admin_client.post(f"{base}/reports/{rid}/sources", data={"kind": "rastreo"},
                                  files={"file": ("x.csv", b"Type,Anchor\nx,y\n", "text/csv")})
    assert res.status_code == 422

    res = await admin_client.put(f"{base}/reports/{rid}/inputs", json={
        "busquedas": 9123, "terminos": [{"q": "restaurantes", "apariciones": 900}],
        "observaciones": "Cerrado el 1 de noviembre", "fecha_rastreo": "2026-11-03"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["datos"]["google"]["busquedas_que_mostraron_ficha"] == 9123
    assert body["datos"]["google"]["consultas"][0]["tipo"] == "Genérica"
    assert body["datos"]["tecnico"]["fecha_ultimo_crawl"] == "3 de noviembre de 2026"

    # Sin los 29 textos no se genera.
    res = await admin_client.post(f"{base}/reports/{rid}/generate")
    assert res.status_code == 422 and "Faltan 29 textos" in res.json()["detail"]

    reference = json.loads((FIXTURES / "datos.json").read_text())
    blocked = next(t for t in body["roadmap"]["meses"]["2026-10"]["tareas"] if t["estado"] == "bloqueado")
    res = await admin_client.patch(f"{base}/reports/{rid}/texts", json={
        "textos": reference["textos"], "editorial": {"resumen": "Lectura «del mes»."},
        "motivos": {str(blocked["tarea_id"]): "Pendiente de que el restaurante confirme horarios."}})
    assert res.status_code == 200, res.text
    assert res.json()["datos"]["editorial"]["resumen"] == "Lectura \"del mes\"."
    res = await admin_client.patch(f"{base}/reports/{rid}/texts", json={"textos": {"inventado": "x"}})
    assert res.status_code == 422

    res = await admin_client.post(f"{base}/reports/{rid}/generate")
    assert res.status_code == 200, res.text
    generated = res.json()
    assert generated["checks"]["ok"], generated["checks"]
    pdf = await admin_client.get(f"{base}/reports/{rid}/files/pdf")
    assert pdf.content == b"%PDF-1.4 falso"
    assert "Cigarral_Seguimiento_Mensual_2026-Octubre.pdf" in pdf.headers["content-disposition"]
    html = await admin_client.get(f"{base}/reports/{rid}/files/html")
    assert html.headers["content-disposition"].startswith("attachment")
    datos_file = (await admin_client.get(f"{base}/reports/{rid}/files/datos")).json()
    assert datos_file["datos"]["textos"]["ficha_vistas_pie"] == reference["textos"]["ficha_vistas_pie"]

    # Editar invalida lo generado.
    res = await admin_client.patch(f"{base}/reports/{rid}/texts", json={"editorial": {"web": "Otra lectura."}})
    assert res.json()["generated_at"] is None
    assert (await admin_client.post(f"{base}/reports/{rid}/deliver")).status_code == 409
    await admin_client.post(f"{base}/reports/{rid}/generate")
    res = await admin_client.post(f"{base}/reports/{rid}/deliver")
    assert res.status_code == 200 and res.json()["delivered_at"]

    # Entregada: congelada. Nueva versión con sus fuentes.
    assert (await admin_client.patch(f"{base}/reports/{rid}/texts", json={"editorial": {"web": "x"}})).status_code == 409
    res = await admin_client.post(f"{base}/reports/{rid}/new-version")
    assert res.status_code == 201, res.text
    copy = res.json()
    assert copy["id"] != rid and copy["delivered_at"] is None and copy["generated_at"] is None
    assert {s["kind"] for s in copy["sources"]} == {"gbp_actual", "rastreo"}
    assert copy["datos"]["editorial"]["web"] == "Otra lectura."


async def test_borrador_de_ia_en_segundo_plano(admin_client, cigarral, db_session):
    report = await _setup(admin_client, cigarral.id)
    row = await db_session.get(ClientLocalReport, report["id"])
    keys = render.required_text_keys("cigarral")
    started = datetime.now(UTC)
    row.ai_status, row.ai_started_at = "running", started
    await db_session.commit()

    async def fake_draft(prompt):
        assert "datos_del_informe" in prompt
        return {"informe": {"modo": "Datos de octubre de 2026", "nota": "Nota."},
                "editorial": {k: f"Lectura {k}." for k in ("resumen", "web", "paginas", "intencion", "grupos",
                                                           "maps", "negocio", "tecnico")},
                "textos": {k: f"Texto {k}." for k in keys}, "tecnico": {}, "motivos": []}

    @asynccontextmanager
    async def same_session():
        yield db_session

    prompt = service.ai.build_prompt("cigarral", row.datos, row.roadmap, text_keys=keys, tone=None)
    await service._run_draft(row.id, prompt, "cigarral", started, draft_fn=fake_draft,
                             session_factory=same_session)
    await db_session.refresh(row)
    assert row.ai_status == "done" and row.ai_error is None
    assert row.datos["textos"]["ficha_vistas_pie"] == "Texto ficha_vistas_pie."

    # Mientras redacta, no se puede editar ni pedir otro.
    row.ai_status, row.ai_started_at = "running", datetime.now(UTC)
    await db_session.commit()
    res = await admin_client.patch(f"/api/clients/{cigarral.id}/local-report/reports/{row.id}/texts",
                                   json={"editorial": {"web": "x"}})
    assert res.status_code == 409


async def test_permisos(make_member_client, cigarral, admin_client):
    report = await _setup(admin_client, cigarral.id)
    base = f"/api/clients/{cigarral.id}/local-report"
    reader = await make_member_client([("digests", True, False)])
    assert (await reader.get(f"{base}/reports/{report['id']}")).status_code == 200
    assert (await reader.post(f"{base}/reports/{report['id']}/generate")).status_code == 403
    outsider = await make_member_client([("clients", True, True)])
    assert (await outsider.get(base)).status_code == 403
    other = await admin_client.get(f"/api/clients/{cigarral.id + 999}/local-report/reports/{report['id']}")
    assert other.status_code == 404


async def test_una_version_abierta_por_periodo(admin_client, cigarral, db_session):
    await _setup(admin_client, cigarral.id)
    res = await admin_client.post(f"/api/clients/{cigarral.id}/local-report/reports", json={})
    assert res.status_code == 409
    res = await admin_client.post(f"/api/clients/{cigarral.id}/local-report/reports",
                                  json={"period_start": "2026-11-01", "period_end": "2026-11-30"})
    assert res.status_code == 422  # todavía no ha terminado
    rows = (await db_session.scalars(select(ClientLocalReport))).all()
    assert len(rows) == 1
