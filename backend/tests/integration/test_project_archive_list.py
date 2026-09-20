"""Lifecycle list filters apply before totals, global ordering and pagination."""
from datetime import datetime, timedelta

from backend.db.models import Client, Project, ProjectStatus


async def test_archive_and_portfolio_paginate_the_complete_filtered_population(
    admin_client, db_session,
):
    client = Client(name="Archive list")
    db_session.add(client)
    await db_session.flush()
    statuses = [ProjectStatus.active, ProjectStatus.completed, ProjectStatus.planning,
                ProjectStatus.cancelled, ProjectStatus.on_hold, ProjectStatus.completed]
    rows = []
    for index, status in enumerate(statuses):
        project = Project(
            name=f"List {index}", client_id=client.id, status=status,
            created_at=datetime(2026, 9, 1) + timedelta(days=index),
            is_recurring=index % 2 == 1,
        )
        db_session.add(project)
        rows.append(project)
    await db_session.commit()
    params = {"client_id": client.id, "page_size": 2}
    for lifecycle, indices in [("portfolio", [4, 2, 0]), ("archive", [5, 3, 1])]:
        found = []
        for page in [1, 2]:
            response = await admin_client.get("/api/projects", params={
                **params, "lifecycle": lifecycle, "page": page,
            })
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["total"] == 3
            found.extend(row["id"] for row in payload["items"])
        assert found == [rows[index].id for index in indices]
    all_rows = await admin_client.get("/api/projects", params={**params, "page_size": 25})
    assert all_rows.json()["total"] == 6
    filtered = await admin_client.get("/api/projects", params={
        **params, "lifecycle": "archive", "status": "completed", "is_recurring": True,
    })
    assert filtered.json()["total"] == 2
    assert [row["id"] for row in filtered.json()["items"]] == [rows[5].id, rows[1].id]
    incompatible = await admin_client.get("/api/projects", params={
        **params, "lifecycle": "portfolio", "status": "completed",
    })
    assert incompatible.json()["total"] == 0
    invalid = await admin_client.get("/api/projects", params={"lifecycle": "anything"})
    assert invalid.status_code == 422
