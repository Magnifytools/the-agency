"""Cohort and observed-source contracts for active client surfaces."""
from datetime import timedelta

import pytest

from backend.db.models import (
    Client,
    ClientStatus,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationLog,
    Task,
    TaskStatus,
)
from backend.services.client_health import (
    HealthCapabilities,
    compute_health,
    compute_health_batch,
)
from backend.services.temporal import utc_now_naive

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


async def test_health_batch_applies_cohort_without_exposing_other_clients(
    admin_client, db_session, monkeypatch,
):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "communications,tasks,digests,finance,billing")
    external = await _client(db_session, "External health")
    internal = await _client(db_session, "Internal health", internal=True)
    await db_session.commit()

    external_response = await admin_client.get(
        "/api/clients/health-scores", params={"cohort": "external"},
    )
    internal_response = await admin_client.get(
        "/api/clients/health-scores", params={"cohort": "internal"},
    )

    assert external_response.status_code == internal_response.status_code == 200
    assert [row["client_id"] for row in external_response.json()] == [external.id]
    assert [row["client_id"] for row in internal_response.json()] == [internal.id]
    for row in external_response.json() + internal_response.json():
        assert row["score"] is None
        assert set(row["factors"].values()) == {None}
        assert set(row["observations"].values()) == {"Fuente no disponible"}
    assert (await admin_client.get(
        "/api/clients/health-scores", params={"cohort": "unknown"},
    )).status_code == 422


async def test_single_and_batch_use_identical_explicit_observation_windows(
    db_session, admin_user,
):
    client = await _client(db_session, "Equivalent observations")
    db_session.add_all([
        CommunicationLog(
            client_id=client.id, occurred_at=utc_now_naive() - timedelta(days=32),
            channel=CommunicationChannel.email, direction=CommunicationDirection.outbound,
            summary="Último contacto", user_id=admin_user.id,
        ),
        Task(
            client_id=client.id, title="Terminada", status=TaskStatus.completed,
        ),
        Task(
            client_id=client.id, title="Vencida", status=TaskStatus.pending,
            due_date=utc_now_naive() - timedelta(days=2),
        ),
    ])
    await db_session.commit()
    capabilities = HealthCapabilities(
        communications=True, tasks=True, digests=False, profitability=False,
    )

    individual = await compute_health(client, db_session, capabilities)
    batch = (await compute_health_batch([client], db_session, capabilities))[0]

    assert batch["observations"] == individual["observations"]
    assert batch["risk_signals"] == individual["risk_signals"]
    assert "riesgo a partir de 31 días" in individual["observations"]["communication"]
    assert individual["observations"]["tasks"] == (
        "Histórico no retirado: 1/2 completadas · 1 atrasadas a fecha de hoy"
    )
    assert individual["observations"]["digests"] == "Fuente no disponible"
    assert individual["observations"]["followups"].startswith("Ahora:")
