"""Cliente antiguo (status finished): fuera de la cartera, con su historial, y reactivable."""
from __future__ import annotations

import pytest

from backend.db.models import Client, ClientStatus, Task, TaskStatus

pytestmark = pytest.mark.integration


async def test_former_client_leaves_the_portfolio_keeps_history_and_can_come_back(admin_client, db_session):
    client = Client(name="Denarius", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    db_session.add(Task(client_id=client.id, title="Auditoría", status=TaskStatus.completed))
    await db_session.commit()

    assert (await admin_client.put(f"/api/clients/{client.id}", json={"status": "finished"})).status_code == 200

    portfolio = (await admin_client.get("/api/clients/portfolio?cohort=all")).json()
    assert client.id not in [row["client_id"] for row in portfolio]
    listed = (await admin_client.get("/api/clients")).json()["items"]
    assert client.id not in [c["id"] for c in listed]
    former = (await admin_client.get("/api/clients?status=finished")).json()["items"]
    assert [c["name"] for c in former] == ["Denarius"]
    # El historial sigue ahí.
    summary = (await admin_client.get(f"/api/clients/{client.id}/summary")).json()
    assert [t["title"] for t in summary["tasks"]] == ["Auditoría"]

    assert (await admin_client.put(f"/api/clients/{client.id}", json={"status": "active"})).status_code == 200
    portfolio = (await admin_client.get("/api/clients/portfolio?cohort=all")).json()
    assert client.id in [row["client_id"] for row in portfolio]
