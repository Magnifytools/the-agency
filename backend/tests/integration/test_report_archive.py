"""Unused generators retire without deleting or widening access to snapshots."""
import json
from datetime import datetime

import pytest
from sqlalchemy import func, select

from backend.db.models import GeneratedReport, ReportType

pytestmark = pytest.mark.integration


async def _report(db, owner_id, title="Informe conservado"):
    row = GeneratedReport(user_id=owner_id, report_type=ReportType.client_status,
                          title=title, generated_at=datetime(2026, 9, 1, 12),
                          content=json.dumps({"summary": "Texto histórico", "sections": [
                              {"title": "Hechos originales", "content": "17 horas registradas"}]}))
    db.add(row)
    await db.flush()
    return row


async def test_retired_generators_do_not_read_sources_or_create_rows(admin_client, db_session):
    before = await db_session.scalar(select(func.count()).select_from(GeneratedReport))
    for path, body in [
        ("/api/reports/generate", {"type": "client_status", "client_id": 99999}),
        ("/api/reports/generate", {"type": "project_status", "project_id": 99999}),
        ("/api/reports/generate", {"type": "weekly_summary"}),
        ("/api/reports/generate-client-monthly", {"client_id": 99999, "year": 2026, "month": 9}),
        ("/api/reports/99999/ai-narrative", {}),
    ]:
        response = await admin_client.post(path, json=body)
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "report_generation_retired"
        assert response.json()["detail"]["href"] == "/digests"
    assert await db_session.scalar(select(func.count()).select_from(GeneratedReport)) == before


async def test_archive_preserves_content_and_owner_acl(admin_client, admin_user, db_session, make_member_client):
    member = await make_member_client([("reports", True, False)])
    own = await _report(db_session, member.test_user.id)
    other = await _report(db_session, admin_user.id, "Archivo de otra persona")
    own_id, other_id = own.id, other.id
    listing = await member.get("/api/reports")
    assert listing.status_code == 200
    assert [r["id"] for r in listing.json()] == [own_id]
    assert listing.json()[0]["sections"][0]["content"] == "17 horas registradas"
    for suffix in ["", "/pdf", "/download"]:
        assert (await member.get(f"/api/reports/{other_id}{suffix}")).status_code == 403
    pdf = await member.get(f"/api/reports/{own_id}/pdf")
    assert pdf.status_code == 200 and "17 horas registradas" in pdf.text
    downloaded = await member.get(f"/api/reports/{own_id}/download")
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"%PDF")
    assert (await member.delete(f"/api/reports/{own_id}")).status_code == 403
    assert (await admin_client.get(f"/api/reports/{other_id}")).status_code == 200
    assert (await member.post("/api/reports/generate", json={"type": "weekly_summary"})).status_code == 403


async def test_archive_ties_paginate_and_validate_bounds(admin_client, admin_user, db_session):
    rows = [await _report(db_session, admin_user.id, f"Archivo {i}") for i in range(23)]
    expected = sorted((r.id for r in rows), reverse=True)
    first = await admin_client.get("/api/reports", params={"limit": 20, "offset": 0})
    second = await admin_client.get("/api/reports", params={"limit": 20, "offset": 20})
    assert [r["id"] for r in first.json() + second.json()] == expected
    for params in [{"limit": 0}, {"limit": 101}, {"offset": -1}]:
        assert (await admin_client.get("/api/reports", params=params)).status_code == 422
