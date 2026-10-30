"""Cohort and observed-source contracts for active client surfaces."""

import pytest

from backend.db.models import (
    Client,
    ClientStatus,
)

pytestmark = pytest.mark.asyncio


async def _client(db_session, name, *, status=ClientStatus.active, internal=False):
    row = Client(name=name, status=status, is_internal=internal)
    db_session.add(row)
    await db_session.flush()
    return row


async def test_client_list_filters_status_and_cohort_before_total_and_page(
    admin_client, db_session,
):
    await _client(db_session, "External active A")
    await _client(db_session, "External active B")
    await _client(db_session, "Internal active", internal=True)
    await _client(db_session, "External paused", status=ClientStatus.paused)
    await _client(db_session, "Internal finished", status=ClientStatus.finished, internal=True)
    await db_session.commit()

    external = await admin_client.get("/api/clients", params={
        "status": "active", "cohort": "external", "page_size": 1, "page": 2,
    })
    internal = await admin_client.get("/api/clients", params={
        "status": "active", "cohort": "internal",
    })
    all_active = await admin_client.get("/api/clients", params={"status": "active"})

    assert external.status_code == internal.status_code == all_active.status_code == 200
    assert external.json()["total"] == 2 and len(external.json()["items"]) == 1
    assert internal.json()["total"] == 1
    assert {row["name"] for row in all_active.json()["items"]} == {
        "External active A", "External active B", "Internal active",
    }
    assert (await admin_client.get("/api/clients", params={"cohort": "partner"})).status_code == 422


async def test_portfolio_applies_cohort_without_exposing_other_clients(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "communications,tasks,digests,timesheet,finance")
    external = await _client(db_session, "External status")
    internal = await _client(db_session, "Internal status", internal=True)
    await db_session.commit()

    external_response = await admin_client.get("/api/clients/portfolio", params={"cohort": "external"})
    internal_response = await admin_client.get("/api/clients/portfolio", params={"cohort": "internal"})

    assert external_response.status_code == internal_response.status_code == 200
    assert [row["client_id"] for row in external_response.json()] == [external.id]
    assert [row["client_id"] for row in internal_response.json()] == [internal.id]
    for row in external_response.json() + internal_response.json():
        # Sin fuentes legibles no hay nada que medir: nunca un "Bien" inventado.
        assert row["status"] == "no_data" and row["reasons"] == []
        assert row["tasks"] is None and row["month"] is None and row["digest"] is None
    assert (await admin_client.get(
        "/api/clients/portfolio", params={"cohort": "unknown"},
    )).status_code == 422
